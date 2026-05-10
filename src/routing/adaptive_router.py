"""Query-time strategy classifier.

Single LLM call with structured output (Pydantic). Cheap model
(``gpt-4.1-nano`` by default) — classification doesn't need frontier
reasoning, and we want this on the hot path of every chat turn.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Iterable

from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from src.config import settings

from .prompts import (
    FEW_SHOT_EXAMPLES,
    NO_SCHEMA_BLOCK,
    ROUTER_SYSTEM_PROMPT,
    SCHEMA_BLOCK_TEMPLATE,
)
from .strategies import SQL_STRATEGIES, Strategy

logger = logging.getLogger(__name__)


class RouterDecision(BaseModel):
    """Structured output of the router LLM call."""

    strategy: Strategy = Field(..., description="The execution strategy to run.")
    reasoning: str = Field(..., description="One-sentence justification.")
    vector_query: str | None = Field(
        default=None,
        description=(
            "Optional standalone search query if the original phrasing is "
            "conversational. Only set when it would meaningfully change "
            "retrieval results."
        ),
    )
    sql_intent: str | None = Field(
        default=None,
        description=(
            "Self-contained natural-language description of the SQL question. "
            "Required for sql_only and hybrid strategies."
        ),
    )
    clarification_question: str | None = Field(
        default=None,
        description=(
            "Single focused follow-up question. Required for clarify strategy."
        ),
    )

    def effective_vector_query(self, fallback: str) -> str:
        return self.vector_query or fallback

    def effective_sql_intent(self, fallback: str) -> str:
        return self.sql_intent or fallback


class AdaptiveRouter:
    """LLM classifier that picks one of :class:`Strategy`."""

    def __init__(
        self,
        *,
        model: str | None = None,
        temperature: float | None = None,
        sql_available: bool = False,
        schema_summary: str | None = None,
    ) -> None:
        self.model = model or settings.ROUTER_MODEL
        self.temperature = (
            temperature if temperature is not None else settings.ROUTER_TEMPERATURE
        )
        self.sql_available = sql_available
        self.schema_summary = schema_summary or ""

        self._llm = ChatOpenAI(
            model=self.model,
            temperature=self.temperature,
            max_tokens=300,
        ).with_structured_output(RouterDecision)

    def classify(
        self,
        query: str,
        history: Iterable[dict[str, str]] | None = None,
    ) -> tuple[RouterDecision, float]:
        """Return ``(decision, latency_ms)``.

        ``history`` is an optional list of prior turns in OpenAI message
        format. Used to disambiguate follow-ups like "what about last
        quarter?" — without it the router would always default to clarify
        on conversational continuations.
        """
        query = (query or "").strip()
        if not query:
            return (
                RouterDecision(
                    strategy=Strategy.CLARIFY,
                    reasoning="Empty input.",
                    clarification_question="Could you share what you'd like to know?",
                ),
                0.0,
            )

        from src.observability import get_callback_handler

        messages = self._build_messages(query, history)
        t0 = time.perf_counter()
        try:
            decision: RouterDecision = self._llm.invoke(
                messages,
                config={
                    "callbacks": get_callback_handler(),
                    "run_name": "router.llm",
                    "metadata": {"langfuse_tags": ["router"]},
                },
            )
        except Exception as exc:
            logger.exception("Router LLM call failed; defaulting to vector_only")
            elapsed = (time.perf_counter() - t0) * 1000
            return (
                RouterDecision(
                    strategy=Strategy.VECTOR_ONLY,
                    reasoning=f"Router fell back to vector_only after error: {exc}",
                    vector_query=query,
                ),
                elapsed,
            )

        elapsed = (time.perf_counter() - t0) * 1000
        decision = self._sanitize(decision, query)
        logger.info(
            f"Router: '{query[:40]}\u2026' \u2192 {decision.strategy} "
            f"({elapsed:.0f}ms) \u00b7 {decision.reasoning}"
        )
        return decision, elapsed

    # ---- internals ----------------------------------------------------

    def _build_messages(
        self,
        query: str,
        history: Iterable[dict[str, str]] | None,
    ) -> list[dict[str, str]]:
        schema_block = (
            SCHEMA_BLOCK_TEMPLATE.format(schema_summary=self.schema_summary)
            if self.sql_available and self.schema_summary
            else NO_SCHEMA_BLOCK
        )

        system_content = f"{ROUTER_SYSTEM_PROMPT}\n\n{schema_block}"
        messages: list[dict[str, str]] = [
            {"role": "system", "content": system_content}
        ]

        # Few-shot examples as prior conversation turns.
        for ex in FEW_SHOT_EXAMPLES:
            assistant_payload = ex["assistant"]
            messages.append({"role": "user", "content": str(ex["user"])})
            messages.append(
                {
                    "role": "assistant",
                    "content": json.dumps(assistant_payload),
                }
            )

        # Real chat history (optional). Skip system messages.
        if history:
            for turn in history:
                role = turn.get("role")
                content = _coerce_content(turn.get("content")).strip()
                if not content or role not in ("user", "assistant"):
                    continue
                messages.append({"role": role, "content": content})

        # The current query.
        messages.append({"role": "user", "content": query})
        return messages

    def _sanitize(
        self,
        decision: RouterDecision,
        query: str,
    ) -> RouterDecision:
        # Hard guard: never pick a SQL strategy if SQL isn't available.
        if not self.sql_available and decision.strategy in SQL_STRATEGIES:
            logger.warning(
                f"Router picked {decision.strategy} but SQL is not configured; "
                "downgrading to vector_only."
            )
            return decision.model_copy(
                update={
                    "strategy": Strategy.VECTOR_ONLY,
                    "reasoning": (
                        f"Originally {decision.strategy.value}; downgraded "
                        "because SQL backend is unavailable."
                    ),
                    "sql_intent": None,
                    "vector_query": decision.vector_query or query,
                }
            )

        # Clarify must come with a question, otherwise it's a useless dead-end.
        if decision.strategy == Strategy.CLARIFY and not decision.clarification_question:
            return decision.model_copy(
                update={
                    "clarification_question": (
                        "Could you give me a bit more detail about what you "
                        "want to know?"
                    )
                }
            )

        return decision


def _coerce_content(value: object) -> str:
    """Gradio 6's Chatbot may surface message content as a string, a list of
    parts, or a component dict. Flatten everything to plain text so the
    router prompt stays well-formed."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(_coerce_content(v) for v in value if v is not None)
    if isinstance(value, dict):
        for key in ("text", "value", "content"):
            if key in value:
                return _coerce_content(value[key])
        return ""
    return str(value)
