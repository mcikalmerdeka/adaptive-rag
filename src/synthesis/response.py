"""Grounded answer synthesis.

Three modes the dispatcher can ask for:

- :meth:`GroundedAnswerer.answer` — chunks-only (vector_only)
- :meth:`GroundedAnswerer.answer_direct` — no retrieval (no_retrieval)
- :meth:`GroundedAnswerer.answer_with_sql` — chunks + SQL data (sql_only / hybrid)

All three share the same citation model: inline ``[n]`` references resolve
to passage numbers, and the optional SQL block is referenced as ``[DB]``
when present so the user knows the number came from the warehouse.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from src.config import settings
from src.retrieval import RetrievedChunk

if TYPE_CHECKING:
    from src.tools import SqlResult

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """You are AdaptiveRAG, a careful research assistant.

Answer the user's question using ONLY the context provided below. If the
answer is not contained in the context, reply exactly: "I don't have
enough information to answer that based on the provided documents." Do
not invent facts.

Citation rules:
- Cite supporting passage(s) using inline brackets like [1] or [2, 3].
- When you use a fact that came from the database query results, cite
  it as [DB] inline (and only when there are SQL results below).
- Place citations directly after the claim they support.
- Do not list "References" at the end — citations are inline only.

Style:
- Be concise and direct.
- Prefer short paragraphs and bullet lists over long prose.
- Use Markdown for formatting (lists, bold, code) when it helps clarity.
"""


DIRECT_SYSTEM_PROMPT = """You are AdaptiveRAG, a friendly assistant.

The user's question does not require any retrieval from internal documents
or databases — answer concisely from your own general knowledge. If the
question is a greeting or small talk, respond naturally. Use Markdown for
formatting when it helps clarity.
"""


_CITATION_PATTERN = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")
_DB_CITATION_PATTERN = re.compile(r"\[DB\]", re.IGNORECASE)


# ---- public dataclasses ---------------------------------------------------


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
    cited_db: bool = False
    model: str = ""

    def has_citations(self) -> bool:
        return bool(self.cited_indices) or self.cited_db


class SynthesisError(Exception):
    """Raised when the LLM call fails."""


# ---- the synthesizer ------------------------------------------------------


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

    # ---- public API ---------------------------------------------------

    def answer(
        self,
        query: str,
        chunks: list[RetrievedChunk],
        *,
        history: Iterable[dict[str, str]] | None = None,
    ) -> AnswerResponse:
        """Vector-only synthesis. Backwards-compatible API."""
        return self._answer_grounded(query, chunks, sql=None, history=history)

    def answer_with_sql(
        self,
        query: str,
        chunks: list[RetrievedChunk],
        sql: "SqlResult | None",
        *,
        history: Iterable[dict[str, str]] | None = None,
    ) -> AnswerResponse:
        """sql_only / hybrid synthesis.

        ``chunks`` may be empty (sql_only). ``sql`` may be ``None`` if the
        SQL step failed and we want to fall back to chunks-only.
        """
        return self._answer_grounded(query, chunks, sql=sql, history=history)

    def answer_direct(
        self,
        query: str,
        *,
        history: Iterable[dict[str, str]] | None = None,
    ) -> AnswerResponse:
        """No-retrieval synthesis (greetings, generic knowledge)."""
        messages: list[Any] = [SystemMessage(content=DIRECT_SYSTEM_PROMPT)]
        if history:
            messages.extend(self._coerce_history(history))
        messages.append(HumanMessage(content=query.strip()))

        try:
            ai_msg = self._llm.invoke(messages)
        except Exception as exc:
            logger.exception("Direct LLM call failed")
            raise SynthesisError(f"LLM synthesis failed: {exc}") from exc

        return AnswerResponse(
            answer=(ai_msg.content or "").strip(),
            model=self.model,
        )

    # ---- internals ----------------------------------------------------

    def _answer_grounded(
        self,
        query: str,
        chunks: list[RetrievedChunk],
        *,
        sql: "SqlResult | None",
        history: Iterable[dict[str, str]] | None,
    ) -> AnswerResponse:
        if not chunks and not sql:
            return AnswerResponse(
                answer=(
                    "I couldn't find anything relevant in the index for "
                    "that question. Try ingesting more sources from the "
                    "**Ingest** tab, then ask again."
                ),
                model=self.model,
            )

        context_block = self._format_context(chunks, sql)
        user_msg = (
            f"{context_block}\n\nUser question: {query.strip()}"
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
        cited_chunks = self._parse_cited_indices(answer_text, max_index=len(chunks))
        cited_db = bool(_DB_CITATION_PATTERN.search(answer_text)) and sql is not None
        citations = self._build_citations(chunks, cited_only=cited_chunks)

        return AnswerResponse(
            answer=answer_text,
            citations=citations,
            used_chunks=chunks,
            cited_indices=cited_chunks,
            cited_db=cited_db,
            model=self.model,
        )

    # ---- formatting helpers -------------------------------------------

    def _format_context(
        self,
        chunks: list[RetrievedChunk],
        sql: "SqlResult | None",
    ) -> str:
        sections: list[str] = []
        if chunks:
            sections.append("Document passages:\n\n" + self._format_passages(chunks))
        if sql is not None:
            sections.append("Database query results:\n\n" + self._format_sql(sql))
        return "\n\n---\n\n".join(sections)

    def _format_passages(self, chunks: list[RetrievedChunk]) -> str:
        lines: list[str] = []
        for i, chunk in enumerate(chunks, start=1):
            label = chunk.citation_label()
            text = chunk.text.strip()
            lines.append(f"[{i}] {label}\n{text}")
        return "\n\n---\n\n".join(lines)

    def _format_sql(self, sql: "SqlResult") -> str:
        intent = sql.intent or "(no NL intent recorded)"
        block = [
            f"Question: {intent}",
            "",
            "SQL executed:",
            "```sql",
            sql.sql,
            "```",
        ]
        if sql.rows:
            preview = self._render_rows_table(sql.columns, sql.rows[:25])
            note = (
                f"\n_({len(sql.rows)} rows total"
                + (", truncated" if sql.truncated else "")
                + ")_"
            )
            block.extend(["", "Results:", preview, note])
        else:
            block.append("\nResults: (no rows returned)")
        return "\n".join(block)

    @staticmethod
    def _render_rows_table(columns: list[str], rows: list[dict[str, Any]]) -> str:
        if not rows:
            return "(no rows)"
        header = "| " + " | ".join(columns) + " |"
        sep = "| " + " | ".join("---" for _ in columns) + " |"
        body = [
            "| " + " | ".join(_render_cell(r.get(c)) for c in columns) + " |"
            for r in rows
        ]
        return "\n".join([header, sep, *body])

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
                snippet = snippet[: self.snippet_chars - 1].rstrip() + "\u2026"
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
    def _coerce_history(history: Iterable[dict[str, Any]]) -> list[Any]:
        from langchain_core.messages import AIMessage

        messages: list[Any] = []
        for turn in history:
            role = turn.get("role")
            content = _coerce_content(turn.get("content"))
            if not content:
                continue
            if role == "user":
                messages.append(HumanMessage(content=content))
            elif role == "assistant":
                messages.append(AIMessage(content=content))
            # Silently drop "system" / unknown — the system prompt is set above.
        return messages


def _render_cell(value: Any) -> str:
    if value is None:
        return ""
    s = str(value)
    # Markdown table cells can't contain unescaped pipes / newlines.
    return s.replace("|", "\\|").replace("\n", " ")


def _coerce_content(value: object) -> str:
    """Gradio 6's Chatbot may surface message content as a string, a list of
    parts, or a component dict. Flatten everything to plain text."""
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
