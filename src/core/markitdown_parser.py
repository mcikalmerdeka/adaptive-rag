"""MarkItDown-based markdown parser.

Handles all native digital formats: PDF (born-digital), DOCX, PPTX, XLSX,
HTML, CSV. Returns a clean markdown string. No OCR routing here — that
decision lives in ``parser_router``. No LLM kwargs either: the vision path
is GLMParser, wired by the router.

MarkItDown is pure library code (no model downloads), so there is no
``warm_up()`` equivalent.
"""

from __future__ import annotations

import logging
from pathlib import Path

from markitdown import MarkItDown

logger = logging.getLogger(__name__)


class MarkItDownParserError(Exception):
    """Raised when MarkItDown conversion fails."""


class MarkItDownParser:
    """Thin wrapper around ``markitdown.MarkItDown``."""

    def __init__(self) -> None:
        self._converter = MarkItDown(enable_plugins=False)
        logger.info("MarkItDownParser initialized (enable_plugins=False)")

    def parse(self, file_path: str | Path) -> str:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")

        try:
            result = self._converter.convert(str(path))
        except Exception as exc:
            raise MarkItDownParserError(
                f"MarkItDown failed on {path.name}: {exc}"
            ) from exc

        markdown = result.markdown or ""
        if not markdown.strip():
            logger.warning(
                f"MarkItDown produced empty markdown: {path.name}"
            )
            return ""

        logger.info(
            f"MarkItDown converted {path.name} → {len(markdown)} chars of markdown"
        )
        return markdown
