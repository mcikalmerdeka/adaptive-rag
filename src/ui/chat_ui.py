"""Chat tab: adaptive routing + grounded answers with citations.

Pipeline per turn:
    user msg
       \u2192 AdaptiveRouter (classify)
       \u2192 dispatch one of [no_retrieval | vector_only | sql_only | hybrid | clarify]
       \u2192 (vector path)  HybridRetriever \u2192 Reranker \u2192 top-K chunks
       \u2192 (sql path)     NL\u2192SQL \u2192 read-only execute \u2192 rows
       \u2192 GroundedAnswerer (chunks + SQL + history) \u2192 answer + citations

The dispatcher is built lazily so the UI starts fast even when SQL or
OpenAI aren't configured.
"""

from __future__ import annotations

import logging
from typing import Any

import gradio as gr

from src.config import settings
from src.routing import AdaptiveAnswer, AdaptiveDispatcher, Strategy
from src.routing.dispatcher import DispatchError

logger = logging.getLogger(__name__)


_dispatcher: AdaptiveDispatcher | None = None


def _get_dispatcher() -> AdaptiveDispatcher:
    global _dispatcher
    if _dispatcher is None:
        _dispatcher = AdaptiveDispatcher()
    return _dispatcher


# ---- formatting helpers ---------------------------------------------------


def _strategy_badge(answer: AdaptiveAnswer) -> str:
    icon = {
        Strategy.NO_RETRIEVAL: "\U0001F4AC",  # speech balloon
        Strategy.VECTOR_ONLY: "\U0001F4DA",   # books
        Strategy.SQL_ONLY: "\U0001F4CA",      # bar chart
        Strategy.HYBRID: "\U0001F517",        # link
        Strategy.CLARIFY: "\u2753",           # question mark
    }.get(answer.strategy, "\u2022")
    return f"{icon} **{answer.strategy_label}**"


def _format_sources_md(answer: AdaptiveAnswer) -> str:
    """Right-pane content: router decision \u2192 SQL block \u2192 chunk citations."""
    blocks: list[str] = []

    # 1. Router decision summary.
    blocks.append(
        f"### {_strategy_badge(answer)}\n"
        f"<sub>{_escape(answer.decision.reasoning)}</sub>"
    )

    # 2. Notes (e.g. SQL fallback messages).
    for note in answer.notes:
        blocks.append(f"> \u26a0 {_escape(note)}")

    # 3. SQL block (if any).
    if answer.sql_result is not None:
        sql = answer.sql_result
        rows_preview = ""
        if sql.rows:
            preview = sql.rows[:5]
            cols = sql.columns
            header = "| " + " | ".join(cols) + " |"
            sep = "| " + " | ".join("---" for _ in cols) + " |"
            body_lines = [
                "| " + " | ".join(_render_cell(r.get(c)) for c in cols) + " |"
                for r in preview
            ]
            extra = (
                f"\n_Showing first {len(preview)} of {sql.row_count} rows"
                + (" (truncated)" if sql.truncated else "")
                + "._"
            )
            rows_preview = "\n".join([header, sep, *body_lines]) + extra
        else:
            rows_preview = "_(no rows returned)_"

        blocks.append(
            "**SQL executed**\n\n"
            f"```sql\n{sql.sql}\n```\n\n"
            f"**Results** ({sql.elapsed_ms:.0f}ms)\n\n{rows_preview}"
        )

    # 4. Chunk citations.
    response = answer.response
    if response is not None and response.used_chunks:
        if response.citations:
            blocks.append(
                f"**{len(response.citations)} chunk citation(s)** "
                f"(from top {len(response.used_chunks)} retrieved):"
            )
            for c in response.citations:
                score_bits: list[str] = []
                if c.rerank_score is not None:
                    score_bits.append(f"rerank `{c.rerank_score:.3f}`")
                score_bits.append(f"hybrid `{c.hybrid_score:.3f}`")
                blocks.append(
                    f"\n**[{c.index}] {_escape(c.label)}**\n"
                    f"<sub>{' \u00b7 '.join(score_bits)} \u00b7 doc_id `{c.doc_id or '?'}`</sub>\n"
                    f"\n> {_escape(c.snippet)}\n"
                )
        else:
            blocks.append(
                f"_LLM did not cite any chunks. {len(response.used_chunks)} were retrieved._"
            )

    if response is None and answer.sql_result is None and answer.strategy not in (
        Strategy.NO_RETRIEVAL,
        Strategy.CLARIFY,
    ):
        blocks.append("_No sources retrieved this turn._")

    return "\n\n".join(blocks)


def _format_debug_md(answer: AdaptiveAnswer) -> str:
    t = answer.timings
    parts = [
        f"<sub>Strategy `{answer.strategy.value}` "
        f"\u00b7 routing {t.routing_ms:.0f}ms"
    ]
    if t.retrieval_ms:
        parts.append(f"retrieval {t.retrieval_ms:.0f}ms")
    if t.sql_ms:
        parts.append(f"sql {t.sql_ms:.0f}ms")
    if t.synthesis_ms:
        parts.append(f"synthesis {t.synthesis_ms:.0f}ms")
    parts.append(f"total {t.total_ms:.0f}ms</sub>")
    return " \u00b7 ".join(parts)


def _format_idle_sources() -> str:
    return "_Sources for the most recent answer will appear here._"


def _format_idle_debug() -> str:
    return (
        f"<sub>Router `{settings.ROUTER_MODEL}` "
        f"\u00b7 LLM `{settings.LLM_MODEL}` "
        f"\u00b7 SQL `{settings.SQL_MODEL}` "
        f"\u00b7 reranker `{settings.RERANKER_MODEL}` "
        f"\u00b7 prefetch `{settings.RETRIEVAL_PREFETCH_K}` "
        f"\u00b7 top-K `{settings.RERANK_TOP_K}`</sub>"
    )


# ---- gradio callbacks -----------------------------------------------------


def _chat_step(
    user_msg: str,
    history: list[dict],
) -> tuple[list[dict], str, str, str]:
    user_msg = (user_msg or "").strip()
    if not user_msg:
        return history, "", _format_idle_sources(), _format_idle_debug()

    history = list(history) + [{"role": "user", "content": user_msg}]

    try:
        answer = _get_dispatcher().answer(user_msg, history=history[:-1])
    except DispatchError as exc:
        logger.exception("Dispatch failed")
        history.append(
            {
                "role": "assistant",
                "content": (
                    "**Adaptive dispatch error.**\n\n"
                    f"`{exc}`\n\n"
                    "Common causes: Qdrant container not running, missing "
                    "OpenAI key, or the SQL backend rejecting the query. "
                    "Check the Postgres + Qdrant containers with "
                    "`docker compose ps`."
                ),
            }
        )
        return history, "", _format_idle_sources(), _format_idle_debug()
    except Exception as exc:
        logger.exception("Unexpected chat failure")
        history.append(
            {
                "role": "assistant",
                "content": f"**Unexpected error.**\n\n`{exc}`",
            }
        )
        return history, "", _format_idle_sources(), _format_idle_debug()

    history.append({"role": "assistant", "content": answer.answer})

    sources_md = _format_sources_md(answer)
    debug_md = _format_debug_md(answer)
    return history, "", sources_md, debug_md


def _clear_chat() -> tuple[list[dict], str, str, str]:
    return [], "", _format_idle_sources(), _format_idle_debug()


def _backend_status() -> str:
    sql_state = (
        "connected" if _get_dispatcher().sql_available else "_disabled (no `SQL_DATABASE_URL`)_"
    )
    return f"<sub>SQL backend: {sql_state}</sub>"


# ---- tab renderer ---------------------------------------------------------


def render_chat_tab() -> None:
    """Build the Chat tab."""
    gr.Markdown(
        """
        ### Ask AdaptiveRAG

        Each question is **routed at query time** to one of five strategies:
        `no_retrieval`, `vector_only`, `sql_only`, `hybrid`, or `clarify`.
        Vector queries hit the Qdrant index (hybrid dense + BM25 + reranker)
        and produce inline `[n]` citations. SQL queries hit the Postgres
        warehouse (read-only, with safety guards) and the LLM cites them
        as `[DB]`. The router's decision and the executed SQL are visible
        in the **Sources** panel on the right.
        """
    )

    with gr.Row():
        with gr.Column(scale=2):
            chatbot = gr.Chatbot(
                height=520,
                avatar_images=(None, None),
                label="AdaptiveRAG chat",
            )

            with gr.Row():
                user_input = gr.Textbox(
                    placeholder=(
                        "Try: \"What does our refund policy cover?\" or "
                        "\"How many refunds last month?\""
                    ),
                    show_label=False,
                    scale=8,
                    autofocus=True,
                    submit_btn=True,
                )
                clear_btn = gr.Button("Clear", scale=1, variant="secondary")

            debug_display = gr.Markdown(value=_format_idle_debug())

        with gr.Column(scale=1):
            gr.Markdown("#### Sources & routing")
            sources_display = gr.Markdown(value=_format_idle_sources())

    user_input.submit(
        fn=_chat_step,
        inputs=[user_input, chatbot],
        outputs=[chatbot, user_input, sources_display, debug_display],
    )

    clear_btn.click(
        fn=_clear_chat,
        inputs=[],
        outputs=[chatbot, user_input, sources_display, debug_display],
    )


# ---- tiny helpers ---------------------------------------------------------


def _escape(s: str) -> str:
    return (s or "").replace("<", "&lt;").replace(">", "&gt;")


def _render_cell(value: Any) -> str:
    if value is None:
        return ""
    return str(value).replace("|", "\\|").replace("\n", " ")
