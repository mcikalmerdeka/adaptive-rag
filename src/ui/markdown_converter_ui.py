"""Gradio UI components for the Document to Markdown Converter.

This module provides the UI layout and event handlers for the Gradio app.
It is kept separate from the entry point to allow flexible project structure.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

import gradio as gr

from src.core.converter import DocumentConverterError, MarkdownConverterService

logger = logging.getLogger(__name__)

_converter_service: MarkdownConverterService | None = None


def _get_service() -> MarkdownConverterService:
    """Get or create the converter service singleton."""
    global _converter_service
    if _converter_service is None:
        _converter_service = MarkdownConverterService()
    return _converter_service


def _format_file_info(file_info) -> str:
    """Format file info for display."""
    if file_info is None:
        return "No file uploaded yet."

    if isinstance(file_info, dict):
        name = file_info.get("name", "Unknown")
        size = file_info.get("size", 0)
        path = file_info.get("path", "")
    elif isinstance(file_info, (str, Path)):
        path = str(file_info)
        name = Path(path).name
        size = Path(path).stat().st_size if Path(path).exists() else 0
    else:
        return f"Unknown file format: {type(file_info)}"

    if size < 1024:
        size_str = f"{size} B"
    elif size < 1024 * 1024:
        size_str = f"{size / 1024:.1f} KB"
    else:
        size_str = f"{size / (1024 * 1024):.1f} MB"

    try:
        info = _get_service().get_file_info(path)
        format_str = info.format.value.upper()
        supported = "✅ Supported" if info.is_supported else "❌ Not Supported"
    except Exception as e:
        format_str = "Unknown"
        supported = f"⚠️ Error: {e}"

    return (
        f"**File:** {name}\n"
        f"**Size:** {size_str}\n"
        f"**Detected Format:** {format_str}\n"
        f"**Status:** {supported}"
    )


def _convert_document(file_info) -> tuple[str, str, str | None]:
    """Convert uploaded document to Markdown."""
    if file_info is None:
        return "", "⚠️ Please upload a file first.", None

    if isinstance(file_info, dict):
        file_path = file_info.get("path", "")
    elif isinstance(file_info, (str, Path)):
        file_path = str(file_info)
    else:
        return "", f"❌ Unsupported file object type: {type(file_info)}", None

    if not file_path or not Path(file_path).exists():
        return "", "❌ File not found. Please upload again.", None

    try:
        service = _get_service()
        info = service.get_file_info(file_path)
        if not info.is_supported:
            supported = ", ".join(service.supported_formats)
            return (
                "",
                f"❌ Unsupported format: {info.format.value}\n"
                f"Supported formats: {supported}",
                None,
            )

        markdown_content = service.convert(file_path)

        if not markdown_content.strip():
            return (
                "",
                "⚠️ The document was converted but produced empty content. "
                "This may happen with scanned images or unsupported content.",
                None,
            )

        temp_dir = Path(tempfile.gettempdir())
        output_path = temp_dir / f"{Path(file_path).stem}.md"
        output_path.write_text(markdown_content, encoding="utf-8")

        status = (
            f"✅ Conversion successful!\n"
            f"📄 Document: {Path(file_path).name}\n"
            f"📏 Markdown length: {len(markdown_content)} characters\n"
            f"💾 Ready for download"
        )

        return markdown_content, status, str(output_path)

    except DocumentConverterError as e:
        logger.error(f"Conversion error: {e}")
        return "", f"❌ Conversion failed:\n{str(e)}", None
    except Exception as e:
        logger.exception("Unexpected error during conversion")
        return "", f"❌ Unexpected error:\n{str(e)}", None


def _clear_all() -> tuple[None, str, str, None]:
    """Clear all fields."""
    return None, "Upload a document to get started.", "", None


def build_app() -> gr.Blocks:
    """Build and return the Gradio application."""
    with gr.Blocks(title="Document to Markdown Converter") as demo:
        gr.Markdown(
            """
            # Document to Markdown Converter

            Upload any supported document and convert it to clean Markdown format.
            This is the first step in the intelligent document processing pipeline.
            """
        )

        with gr.Row():
            with gr.Column(scale=1):
                gr.Markdown("### 📤 Upload Document")

                # NOTE: We intentionally do NOT set file_types here.
                # Gradio 6's front-end file type validation is unreliable with
                # certain browsers / extensions. Our back-end (_convert_document)
                # already validates the format and returns a clear error message.
                file_input = gr.File(
                    label="Select a file",
                    file_count="single",
                    type="filepath",
                )

                file_info_display = gr.Markdown(
                    value="Upload a document to get started."
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

                status_display = gr.Textbox(
                    label="Status",
                    lines=4,
                    interactive=False,
                )

                download_btn = gr.DownloadButton(
                    label="⬇️ Download Markdown",
                    variant="primary",
                    size="lg",
                    visible=False,
                )

                with gr.Accordion("ℹ️ Supported Formats", open=False):
                    gr.Markdown(_get_service().detector.supported_formats_text)

            with gr.Column(scale=2):
                gr.Markdown("### 📝 Markdown Preview")

                # Gradio 6 uses `buttons` instead of `show_copy_button`
                markdown_preview = gr.Textbox(
                    label="Converted Markdown",
                    lines=25,
                    max_lines=30,
                    interactive=False,
                    buttons=["copy"],
                    autoscroll=False,
                )

        # Event handlers
        file_input.change(
            fn=_format_file_info,
            inputs=file_input,
            outputs=file_info_display,
        )

        convert_btn.click(
            fn=_convert_document,
            inputs=file_input,
            outputs=[markdown_preview, status_display, download_btn],
        )

        clear_btn.click(
            fn=_clear_all,
            inputs=[],
            outputs=[file_input, file_info_display, status_display, download_btn],
        )

        gr.Markdown(
            """
            ---
            Powered by [Docling](https://github.com/docling-project/docling) |
            Built with [Gradio](https://gradio.app)
            """
        )

    return demo
