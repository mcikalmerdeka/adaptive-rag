"""Docling-based markdown parser.

Handles all native digital formats: PDF (born-digital), DOCX, PPTX, XLSX,
HTML, CSV. Returns a clean markdown string. No OCR routing here — that
decision lives in ``parser_router``.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

# Hugging Face Hub tries to create symlinks by default on Windows, which
# requires admin rights or Developer Mode. Disabling symlinks forces copies
# instead, avoiding WinError 1314 during Docling's first-run model download.
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS", "1")

from docling.datamodel.document import ConversionResult
from docling.document_converter import DocumentConverter

logger = logging.getLogger(__name__)


class DoclingParserError(Exception):
    """Raised when Docling conversion fails."""


class DoclingParser:
    """Thin wrapper around ``docling.DocumentConverter``."""

    def __init__(self) -> None:
        self._converter = DocumentConverter()
        logger.info("DoclingParser initialized")

    def parse(self, file_path: str | Path) -> str:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")

        try:
            result: ConversionResult = self._converter.convert(str(path))
        except Exception as exc:
            raise DoclingParserError(
                f"Docling failed on {path.name}: {exc}"
            ) from exc

        if result.status.name != "SUCCESS":
            raise DoclingParserError(
                f"Docling status {result.status.name} for {path.name}"
            )

        markdown = result.document.export_to_markdown() or ""
        if not markdown.strip():
            logger.warning(f"Docling produced empty markdown: {path.name}")
            return ""

        logger.info(
            f"Docling converted {path.name} → {len(markdown)} chars of markdown"
        )
        return markdown
