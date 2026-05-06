"""Chat tab: ask questions, get grounded answers with citations.

Pipeline per turn:
    user msg → HybridRetriever → Reranker → top-K chunks → ChatOpenAI →
    answer + numbered citations.

The Qdrant store, reranker and LLM are all built lazily on first use so
the UI starts fast even before any of those are configured.
"""

from __future__ import annotations

import logging

import gradio as gr

from src.config import settings
from src.retrieval import RetrievalPipeline
from src.synthesis import AnswerResponse, GroundedAnswerer, SynthesisError

logger = logging.getLogger(__name__)


_pipeline: RetrievalPipeline | None = None
_answerer: GroundedAnswerer | None = None


def _get_pipeline() -> RetrievalPipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = RetrievalPipeline()
    return _pipeline


def _get_answerer() -> GroundedAnswerer:
    global _answerer
    if _answerer is None:
        _answerer = GroundedAnswerer()
    return _answerer


def _format_sources_md(response: AnswerResponse) -> str:
    if not response.used_chunks:
        return "_No chunks were retrieved for this turn._"

    citations = response.citations
    if not citations:
        return "_LLM did not cite any chunks. All retrieved chunks shown below._"

    lines: list[str] = [
        f"**{len(citations)} source(s) cited** "
        f"(from top {len(response.used_chunks)} retrieved):"
    ]
    for c in citations:
        score_bits = []
        if c.rerank_score is not None:
            score_bits.append(f"rerank `{c.rerank_score:.3f}`")
        score_bits.append(f"hybrid `{c.hybrid_score:.3f}`")
        score_str = " · ".join(score_bits)

        lines.append(f"\n**[{c.index}] {c.label}**")
        lines.append(f"<sub>{score_str} · doc_id `{c.doc_id or '?'}`</sub>")
        lines.append(f"\n> {c.snippet}\n")
    return "\n".join(lines)


def _chat_step(
    user_msg: str,
    history: list[dict],
) -> tuple[list[dict], str, str, str]:
    user_msg = (user_msg or "").strip()
    if not user_msg:
        return history, "", _format_idle_sources(), _format_idle_debug()

    history = list(history) + [{"role": "user", "content": user_msg}]

    try:
        report = _get_pipeline().retrieve(user_msg)
    except Exception as exc:
        logger.exception("Retrieval failed")
        history.append(
            {
                "role": "assistant",
                "content": (
                    f"**Retrieval error.** I couldn't reach the vector index.\n\n"
                    f"`{exc}`\n\n"
                    "If you're using Docker Qdrant, make sure the container is "
                    "running (`docker compose up -d qdrant`). If you're using "
                    "embedded mode, comment out `QDRANT_URL` in `.env`."
                ),
            }
        )
        return history, "", _format_idle_sources(), _format_idle_debug()

    if report.final_count == 0:
        history.append(
            {
                "role": "assistant",
                "content": (
                    "I couldn't find anything in the index for that. "
                    "Have you ingested any documents in the **Ingest** tab yet?"
                ),
            }
        )
        return history, "", _format_idle_sources(), _format_idle_debug()

    try:
        response = _get_answerer().answer(
            user_msg,
            report.chunks,
            history=history[:-1],  # everything except the just-appended user turn
        )
    except SynthesisError as exc:
        logger.exception("Synthesis failed")
        history.append(
            {
                "role": "assistant",
                "content": (
                    f"**LLM error.** Retrieval succeeded "
                    f"({report.final_count} chunks) but synthesis failed.\n\n"
                    f"`{exc}`"
                ),
            }
        )
        return history, "", _format_idle_sources(), _format_idle_debug()

    history.append({"role": "assistant", "content": response.answer})

    sources_md = _format_sources_md(response)
    debug_md = (
        f"<sub>Model: `{response.model}` · "
        f"Reranker `{settings.RERANKER_MODEL}` "
        f"({'used' if report.reranker_used else 'skipped'}) · "
        f"prefetch={report.fused_count} ({report.fused_ms:.0f}ms) → "
        f"top {report.final_count} (rerank {report.rerank_ms:.0f}ms)</sub>"
    )

    return history, "", sources_md, debug_md


def _format_idle_sources() -> str:
    return "_Sources for the most recent answer will appear here._"


def _format_idle_debug() -> str:
    return (
        f"<sub>Reranker `{settings.RERANKER_MODEL}` · "
        f"Prefetch K `{settings.RETRIEVAL_PREFETCH_K}` · "
        f"Top K `{settings.RERANK_TOP_K}` · "
        f"LLM `{settings.LLM_MODEL}`</sub>"
    )


def _clear_chat() -> tuple[list[dict], str, str, str]:
    return [], "", _format_idle_sources(), _format_idle_debug()


def render_chat_tab() -> None:
    """Build the Chat tab."""
    gr.Markdown(
        """
        ### Ask your indexed documents

        Each question runs **hybrid search** (dense + BM25) over the Qdrant
        collection, the top candidates are **reranked** with a cross-encoder,
        and a grounded answer is synthesized from the top
        **`RERANK_TOP_K`** chunks. Citations are inline (e.g. `[2]`) and the
        sources panel below shows what the LLM actually used.
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
                    placeholder="Ask anything about your indexed documents…",
                    show_label=False,
                    scale=8,
                    autofocus=True,
                    submit_btn=True,
                )
                clear_btn = gr.Button("Clear", scale=1, variant="secondary")

            debug_display = gr.Markdown(value=_format_idle_debug())

        with gr.Column(scale=1):
            gr.Markdown("#### Sources")
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
