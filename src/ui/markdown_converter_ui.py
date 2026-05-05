"""Gradio UI for the Document → Markdown step.

Lets the user upload a file, see what parser was selected (Docling /
Qwen3-VL / passthrough), preview the markdown, and download it.

A "Force Qwen3-VL OCR for PDFs" checkbox overrides the born-digital
heuristic when the user knows OCR quality matters (mathematical layouts,
tightly packed tables, scanned docs the heuristic misses).
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

import gradio as gr
from dotenv import load_dotenv

from src.core import DocumentConverterError, MarkdownConverterService
from src.core.qwen_parser import QwenParser

load_dotenv()

logger = logging.getLogger(__name__)

_service: MarkdownConverterService | None = None


def _get_service() -> MarkdownConverterService:
    global _service
    if _service is None:
        _service = MarkdownConverterService()
    return _service


# ---- helpers ----------------------------------------------------------


def _resolve_path(file_info) -> str | None:
    if file_info is None:
        return None
    if isinstance(file_info, dict):
        return file_info.get("path") or None
    if isinstance(file_info, (str, Path)):
        return str(file_info)
    return None


def _human_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / (1024 * 1024):.1f} MB"


def _format_file_info(file_info) -> str:
    file_path = _resolve_path(file_info)
    if not file_path:
        return "Upload a document to get started."

    p = Path(file_path)
    if not p.exists():
        return f"File not found: {p.name}"

    size_str = _human_size(p.stat().st_size)
    try:
        info = _get_service().get_file_info(file_path)
        format_str = info.format.value.upper()
        supported = (
            "Supported" if info.is_supported else "Not supported"
        )
    except Exception as exc:
        format_str = "Unknown"
        supported = f"Error: {exc}"

    return (
        f"**File:** {p.name}\n\n"
        f"**Size:** {size_str}\n\n"
        f"**Detected format:** {format_str}\n\n"
        f"**Status:** {supported}"
    )


def _convert_document(
    file_info,
    force_qwen_for_pdf: bool,
    progress: gr.Progress = gr.Progress(),
) -> tuple[str, str, gr.DownloadButton]:
    file_path = _resolve_path(file_info)
    if not file_path:
        return "", "Please upload a file first.", gr.DownloadButton(visible=False)

    if not Path(file_path).exists():
        return "", "File not found. Please upload again.", gr.DownloadButton(visible=False)

    service = _get_service()

    try:
        info = service.get_file_info(file_path)
        if not info.is_supported:
            supported = ", ".join(service.supported_formats)
            return (
                "",
                f"Unsupported format: {info.format.value}\nSupported: {supported}",
                gr.DownloadButton(visible=False),
            )

        progress(0, desc="Converting...")

        def _on_page(current: int, total: int) -> None:
            progress(current / total, desc=f"OCR page {current}/{total}")

        output = service.convert_detailed(
            file_path,
            force_qwen_for_pdf=force_qwen_for_pdf,
            progress=_on_page,
        )

        if not output.markdown.strip():
            return (
                "",
                "Converted successfully but produced empty content.",
                gr.DownloadButton(visible=False),
            )

        out_dir = Path(tempfile.gettempdir())
        out_path = out_dir / f"{Path(file_path).stem}.md"
        out_path.write_text(output.markdown, encoding="utf-8")

        pages_str = (
            f" ({output.pages} pages)" if output.pages and output.pages > 1 else ""
        )
        status = (
            f"Conversion successful.\n\n"
            f"**Document:** {info.path.name}\n"
            f"**Parser:** `{output.parser}`{pages_str}\n"
            f"**Markdown size:** {len(output.markdown)} characters"
        )

        return (
            output.markdown,
            status,
            gr.DownloadButton(value=str(out_path), visible=True),
        )

    except DocumentConverterError as exc:
        logger.error(f"Conversion error: {exc}")
        return (
            "",
            f"Conversion failed:\n{exc}",
            gr.DownloadButton(visible=False),
        )
    except Exception as exc:
        logger.exception("Unexpected error during conversion")
        return (
            "",
            f"Unexpected error:\n{exc}",
            gr.DownloadButton(visible=False),
        )


def _clear_all():
    return (
        None,
        "Upload a document to get started.",
        "",
        "",
        gr.DownloadButton(visible=False),
    )


# ---- layout -----------------------------------------------------------


def build_app() -> gr.Blocks:
    qwen_available = QwenParser.is_configured()
    qwen_note = (
        "Qwen3-VL is configured. Images and scanned PDFs will use it automatically."
        if qwen_available
        else "QWEN_API_KEY not set. Image and scanned-PDF OCR will fail. "
        "Add it to .env to enable."
    )

    with gr.Blocks(title="AdaptiveRAG — Document → Markdown") as demo:
        gr.Markdown(
            """
            # AdaptiveRAG — Document → Markdown

            Upload a document and convert it to clean markdown. The router
            picks the best parser per file:

            - **Docling** for `.pdf` (born-digital), `.docx`, `.pptx`, `.xlsx`, `.html`, `.csv`
            - **Qwen3-VL** for images and scanned PDFs
            - **Passthrough** for `.md` and `.txt`
            """
        )

        with gr.Row():
            with gr.Column(scale=1):
                gr.Markdown("### Upload")

                file_input = gr.File(
                    label="Select a file",
                    file_count="single",
                    type="filepath",
                )

                file_info_display = gr.Markdown(
                    value="Upload a document to get started."
                )

                force_qwen = gr.Checkbox(
                    label="Force Qwen3-VL OCR for PDFs",
                    value=False,
                    info=(
                        "Override the born-digital heuristic. Use when "
                        "Docling's output is poor on complex layouts. "
                        "Will incur Qwen API costs."
                    ),
                    interactive=qwen_available,
                )

                with gr.Row():
                    convert_btn = gr.Button(
                        "Convert to Markdown",
                        variant="primary",
                        size="lg",
                    )
                    clear_btn = gr.Button(
                        "Clear",
                        variant="secondary",
                        size="lg",
                    )

                status_display = gr.Markdown(value="")

                download_btn = gr.DownloadButton(
                    label="Download Markdown",
                    variant="primary",
                    size="lg",
                    visible=False,
                )

                with gr.Accordion("Supported formats", open=False):
                    gr.Markdown(_get_service().detector.supported_formats_text)

                gr.Markdown(f"_{qwen_note}_")

            with gr.Column(scale=2):
                gr.Markdown("### Markdown preview")

                markdown_preview = gr.Textbox(
                    label="Converted Markdown",
                    lines=25,
                    max_lines=30,
                    interactive=False,
                    buttons=["copy"],
                    autoscroll=False,
                )

        file_input.change(
            fn=_format_file_info,
            inputs=file_input,
            outputs=file_info_display,
        )

        convert_btn.click(
            fn=_convert_document,
            inputs=[file_input, force_qwen],
            outputs=[markdown_preview, status_display, download_btn],
        )

        clear_btn.click(
            fn=_clear_all,
            inputs=[],
            outputs=[
                file_input,
                file_info_display,
                status_display,
                markdown_preview,
                download_btn,
            ],
        )

        gr.Markdown(
            """
            ---
            Powered by [Docling](https://github.com/docling-project/docling)
            and [Qwen3-VL](https://help.aliyun.com/zh/dashscope/) ·
            Built with [Gradio](https://gradio.app)
            """
        )

    return demo
