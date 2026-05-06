"""Main entry point for the AdaptiveRAG Gradio application.

Run:
    uv run app.py
"""

from __future__ import annotations

import logging

from src.core.converter import MarkdownConverterService
from src.ui import build_app

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def main() -> None:
    logger.info("Warming up document converter (Docling models may download on first run)...")
    MarkdownConverterService()
    logger.info("Converter ready.")

    app = build_app()
    app.launch(
        server_name="0.0.0.0",
        server_port=7860,
        share=False,
        show_error=True,
    )


if __name__ == "__main__":
    main()
