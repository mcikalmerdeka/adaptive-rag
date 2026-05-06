"""Grounded answer synthesis.

Pipeline:
1. Receive a query + ranked :class:`RetrievedChunk` list.
2. Number each chunk ``[1]..[N]`` and build a context block.
3. Call the LLM with a strict system prompt that requires inline ``[n]``
   citations and refuses to invent facts.
4. Return the answer text + a parallel list of :class:`Citation` objects
   the UI can render as cards / links.

We deliberately keep this layer thin (no agent loop, no tool calling) —
adaptive routing comes in Phase 5.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from src.config import settings
from src.retrieval import RetrievedChunk

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """You are AdaptiveRAG, a careful research assistant.

Answer the user's question using ONLY the numbered context passages
provided below. If the answer is not contained in the context, reply
exactly: "I don't have enough information to answer that based on the
provided documents." Do not invent facts.

Citation rules:
- Cite the supporting passage(s) using inline brackets like [1] or [2, 3].
- Place citations directly after the claim they support.
- Do not list "References" at the end — citations are inline only.

Style:
- Be concise and direct.
- Prefer short paragraphs and bullet lists over long prose.
- Use Markdown for formatting (lists, bold, code) when it helps clarity.
"""


CONTEXT_TEMPLATE = """Context passages:

{passages}

User question: {query}
"""


_CITATION_PATTERN = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")


@dataclass
class Citation:
    """A single citation as exposed to the UI / API."""

    index: int               # 1-based, matches the [n] in the answer
    label: str               # human readable, e.g. "policy.pdf > Refunds"
    snippet: str             # short text preview from the chunk
    source: str | None       # absolute path of the original file
    doc_id: str | None
    rank: int
    rerank_score: float | None
    hybrid_score: float


@dataclass
class AnswerResponse:
    """The full result of a chat turn."""

    answer: str
    citations: list[Citation] = field(default_factory=list)
    used_chunks: list[RetrievedChunk] = field(default_factory=list)
    cited_indices: list[int] = field(default_factory=list)
    model: str = ""

    def has_citations(self) -> bool:
        return bool(self.cited_indices)


class SynthesisError(Exception):
    """Raised when the LLM call fails."""


class GroundedAnswerer:
    """LLM-backed synthesizer that respects retrieved context."""

    def __init__(
        self,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        snippet_chars: int = 240,
    ) -> None:
        if not settings.OPENAI_API_KEY:
            raise SynthesisError(
                "OPENAI_API_KEY is not set. The chat layer needs it to call "
                "the synthesis LLM."
            )
        self.model = model or settings.LLM_MODEL
        self.temperature = (
            temperature if temperature is not None else settings.LLM_TEMPERATURE
        )
        self.max_tokens = max_tokens or settings.LLM_MAX_TOKENS
        self.snippet_chars = snippet_chars

        self._llm = ChatOpenAI(
            model=self.model,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )

    def answer(
        self,
        query: str,
        chunks: list[RetrievedChunk],
        *,
        history: Iterable[dict[str, str]] | None = None,
    ) -> AnswerResponse:
        """Synthesize an answer from ``chunks``.

        ``history`` is an optional list of prior chat turns in OpenAI
        message format, e.g. ``[{"role": "user", "content": ...}, ...]``.
        It's threaded into the LLM call so follow-ups feel natural, but we
        do NOT use it for retrieval (each turn is retrieved fresh).
        """
        if not chunks:
            return AnswerResponse(
                answer=(
                    "I couldn't find any indexed documents related to your "
                    "question. Try ingesting more sources from the **Ingest** "
                    "tab, then ask again."
                ),
                model=self.model,
            )

        passages_block = self._format_passages(chunks)
        user_msg = CONTEXT_TEMPLATE.format(
            passages=passages_block,
            query=query.strip(),
        )

        messages: list[Any] = [SystemMessage(content=SYSTEM_PROMPT)]
        if history:
            messages.extend(self._coerce_history(history))
        messages.append(HumanMessage(content=user_msg))

        try:
            ai_msg = self._llm.invoke(messages)
        except Exception as exc:
            logger.exception("LLM synthesis failed")
            raise SynthesisError(f"LLM synthesis failed: {exc}") from exc

        answer_text = (ai_msg.content or "").strip()
        cited = self._parse_cited_indices(answer_text, max_index=len(chunks))
        citations = self._build_citations(chunks, cited_only=cited)

        return AnswerResponse(
            answer=answer_text,
            citations=citations,
            used_chunks=chunks,
            cited_indices=cited,
            model=self.model,
        )

    # ---- formatting helpers -------------------------------------------

    def _format_passages(self, chunks: list[RetrievedChunk]) -> str:
        lines: list[str] = []
        for i, chunk in enumerate(chunks, start=1):
            label = chunk.citation_label()
            text = chunk.text.strip()
            lines.append(f"[{i}] {label}\n{text}")
        return "\n\n---\n\n".join(lines)

    def _build_citations(
        self,
        chunks: list[RetrievedChunk],
        *,
        cited_only: list[int],
    ) -> list[Citation]:
        # When the LLM cited specific indices, only return those (clean UI).
        # When it cited none, surface all retrieved chunks so the user can
        # still see "where this came from" — useful for debugging.
        indices = cited_only or list(range(1, len(chunks) + 1))
        out: list[Citation] = []
        for idx in indices:
            if idx < 1 or idx > len(chunks):
                continue
            chunk = chunks[idx - 1]
            meta = chunk.metadata
            snippet = chunk.text.strip().replace("\n", " ")
            if len(snippet) > self.snippet_chars:
                snippet = snippet[: self.snippet_chars - 1].rstrip() + "…"
            out.append(
                Citation(
                    index=idx,
                    label=chunk.citation_label(),
                    snippet=snippet,
                    source=meta.get("source"),
                    doc_id=meta.get("doc_id"),
                    rank=chunk.rank or idx,
                    rerank_score=chunk.rerank_score,
                    hybrid_score=chunk.hybrid_score,
                )
            )
        return out

    @staticmethod
    def _parse_cited_indices(answer: str, *, max_index: int) -> list[int]:
        seen: list[int] = []
        for match in _CITATION_PATTERN.finditer(answer):
            for raw in match.group(1).split(","):
                try:
                    n = int(raw.strip())
                except ValueError:
                    continue
                if 1 <= n <= max_index and n not in seen:
                    seen.append(n)
        return seen

    @staticmethod
    def _coerce_history(history: Iterable[dict[str, str]]) -> list[Any]:
        from langchain_core.messages import AIMessage

        messages: list[Any] = []
        for turn in history:
            role = turn.get("role")
            content = turn.get("content") or ""
            if not content:
                continue
            if role == "user":
                messages.append(HumanMessage(content=content))
            elif role == "assistant":
                messages.append(AIMessage(content=content))
            # Silently drop "system" / unknown — the system prompt is set above.
        return messages
