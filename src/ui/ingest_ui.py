"""Ingest tab: upload → convert → chunk → index in Qdrant.

The Qdrant store is built lazily on first ingestion to avoid paying its
init cost (model download, file lock) when the user only wants to use the
Convert tab.
"""

from __future__ import annotations

import logging
from pathlib import Path

import gradio as gr

from src.core import MarkdownConverterService
from src.core.qwen_parser import QwenParser
from src.indexing import IngestionPipeline, IngestionResult

logger = logging.getLogger(__name__)


_pipeline: IngestionPipeline | None = None


def _get_pipeline() -> IngestionPipeline:
    global _pipeline
    if _pipeline is None:
        # Reuse the converter service that may already be warm in the
        # Convert tab. Qdrant client is built lazily inside the pipeline.
        _pipeline = IngestionPipeline(converter=MarkdownConverterService())
    return _pipeline


def _resolve_paths(files) -> list[str]:
    if not files:
        return []
    if not isinstance(files, list):
        files = [files]
    out: list[str] = []
    for f in files:
        if isinstance(f, dict):
            p = f.get("path")
        else:
            p = f
        if p:
            out.append(str(p))
    return out


def _format_result(r: IngestionResult) -> str:
    if r.skipped:
        return (
            f"**{r.file_path.name}** — already indexed (doc_id `{r.doc_id}`). "
            "Skipped."
        )
    if r.chunks_indexed == 0:
        return (
            f"**{r.file_path.name}** — produced 0 chunks (empty parse output). "
            f"parser=`{r.parser}`"
        )
    pages_str = f", {r.pages} pages" if r.pages else ""
    return (
        f"**{r.file_path.name}** — indexed `{r.chunks_indexed}` chunks "
        f"(parser=`{r.parser}`{pages_str}, "
        f"{r.markdown_chars:,} markdown chars, doc_id `{r.doc_id}`)"
    )


def _ingest_files(
    files,
    force_qwen_for_pdf: bool,
    skip_if_exists: bool,
    progress: gr.Progress = gr.Progress(),
) -> tuple[str, str]:
    paths = _resolve_paths(files)
    if not paths:
        return "Upload at least one file.", _library_table_md()

    pipeline = _get_pipeline()

    lines: list[str] = []
    total = len(paths)
    for idx, path in enumerate(paths, start=1):
        progress((idx - 1) / total, desc=f"Ingesting {Path(path).name}")
        try:
            def _on_page(current: int, n_pages: int, _idx=idx, _total=total) -> None:
                # Map per-file OCR progress into overall progress bar.
                file_fraction = (current / n_pages) if n_pages else 1.0
                overall = ((_idx - 1) + file_fraction) / _total
                progress(overall, desc=f"OCR page {current}/{n_pages} of {Path(path).name}")

            result = pipeline.ingest(
                path,
                force_qwen_for_pdf=force_qwen_for_pdf,
                skip_if_exists=skip_if_exists,
                replace_existing=not skip_if_exists,
                ocr_progress=_on_page,
            )
            lines.append(f"- {_format_result(result)}")
        except Exception as exc:
            logger.exception(f"Ingestion failed for {path}")
            lines.append(f"- **{Path(path).name}** — failed: `{exc}`")

    progress(1.0, desc="Done")

    summary = "\n".join(lines)
    return summary, _library_table_md()


def _library_table_md() -> str:
    """Render the current library of indexed documents as a markdown table."""
    try:
        pipeline = _get_pipeline()
        docs = pipeline.store.list_documents()
        total_chunks = pipeline.store.total_chunks()
    except Exception as exc:
        return f"Could not read library: `{exc}`"

    if not docs:
        return f"_No documents indexed yet. Total chunks: {total_chunks}._"

    header = (
        "| Filename | Parser | Chunks | Ingested | doc_id |\n"
        "|---|---|---|---|---|"
    )
    rows = [
        f"| {d.get('filename') or '?'} "
        f"| `{d.get('parser') or '?'}` "
        f"| {d.get('total_chunks') or '?'} "
        f"| {d.get('ingested_at') or '?'} "
        f"| `{d.get('doc_id')}` |"
        for d in docs
    ]
    return (
        f"**{len(docs)} document(s) · {total_chunks} total chunks**\n\n"
        + "\n".join([header, *rows])
    )


def _refresh_library() -> str:
    return _library_table_md()


def _delete_doc(doc_id: str) -> tuple[str, str]:
    doc_id = (doc_id or "").strip()
    if not doc_id:
        return "Provide a doc_id to delete.", _library_table_md()
    try:
        n = _get_pipeline().store.delete_doc(doc_id)
    except Exception as exc:
        return f"Delete failed: `{exc}`", _library_table_md()

    if n == 0:
        return f"No chunks found for doc_id `{doc_id}`.", _library_table_md()
    return f"Deleted **{n}** chunks for doc_id `{doc_id}`.", _library_table_md()


def render_ingest_tab() -> None:
    """Build the Ingest tab."""
    qwen_available = QwenParser.is_configured()

    gr.Markdown(
        """
        ### Ingest documents into the vector index

        Each file is converted to markdown, chunked by header, and upserted
        into Qdrant with both dense (OpenAI `text-embedding-3-small`) and
        sparse (BM25) vectors. Re-ingesting the same file replaces its
        previous chunks unless **Skip if already indexed** is on.
        """
    )

    with gr.Row():
        with gr.Column(scale=1):
            gr.Markdown("#### Upload")

            file_input = gr.File(
                label="Select one or more files",
                file_count="multiple",
                type="filepath",
            )

            with gr.Row():
                force_qwen = gr.Checkbox(
                    label="Force Qwen3-VL OCR for PDFs",
                    value=False,
                    interactive=qwen_available,
                )
                skip_existing = gr.Checkbox(
                    label="Skip if already indexed",
                    value=False,
                    info="If on, files with a matching doc_id are not re-processed.",
                )

            ingest_btn = gr.Button(
                "Ingest into Qdrant",
                variant="primary",
                size="lg",
            )

            status_display = gr.Markdown(
                value="_Upload files and click 'Ingest into Qdrant' to begin._"
            )

        with gr.Column(scale=1):
            gr.Markdown("#### Library")

            library_display = gr.Markdown(value=_library_table_md())

            with gr.Row():
                refresh_btn = gr.Button("Refresh library", size="sm")

            with gr.Accordion("Delete a document", open=False):
                delete_input = gr.Textbox(
                    label="doc_id",
                    placeholder="e.g. a3f5b8c1d2e4f6a7",
                )
                delete_btn = gr.Button("Delete", variant="stop", size="sm")
                delete_status = gr.Markdown(value="")

    ingest_btn.click(
        fn=_ingest_files,
        inputs=[file_input, force_qwen, skip_existing],
        outputs=[status_display, library_display],
    )

    refresh_btn.click(fn=_refresh_library, inputs=[], outputs=library_display)

    delete_btn.click(
        fn=_delete_doc,
        inputs=[delete_input],
        outputs=[delete_status, library_display],
    )
