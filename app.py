"""Main entry point for the Document to Markdown Converter.

Run this file directly to start the Gradio web application:
    uv run app.py
"""

from __future__ import annotations

import logging

import gradio as gr

from src.core.converter import MarkdownConverterService
from src.ui.markdown_converter_ui import build_app

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def main() -> None:
    """Run the Gradio application."""
    logger.info("Initializing Document Converter Service...")
    MarkdownConverterService()  # warm-up
    logger.info("Converter ready!")

    app = build_app()
    app.launch(
        server_name="0.0.0.0",
        server_port=7860,
        share=False,
        show_error=True,
    )


if __name__ == "__main__":
    main()
