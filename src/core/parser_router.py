"""Routing logic: pick the right parser per file type.

Decision table:

    .md / .txt                                 → passthrough (read file)
    .png / .jpg / .jpeg / .webp                → Qwen
    .pdf scanned (heuristic)                   → Qwen (page-by-page, cached)
    .pdf born-digital                          → Docling
    .docx / .pptx / .xlsx / .html / .csv       → Docling

A ``force_qwen_for_pdf`` flag lets the UI override the heuristic when the
user knows the OCR quality matters (e.g. mathematical layouts, tight tables).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from src.utils import is_scanned_pdf

from .docling_parser import DoclingParser
from .file_detector import DocumentFormat, FileTypeInfo
from .qwen_parser import QwenParser, QwenParserError

logger = logging.getLogger(__name__)


@dataclass
class ParseResult:
    markdown: str
    parser: str  # "docling" | "qwen3-vl" | "passthrough"
    pages: int | None = None  # only set for PDFs


class ParserRouter:
    """Dispatch a file to the appropriate parser based on type + content."""

    def __init__(
        self,
        docling: DoclingParser | None = None,
        qwen: QwenParser | None = None,
    ) -> None:
        self._docling = docling
        self._qwen = qwen

    # Lazy init so we don't pay startup cost for parsers we may never use.

    def _get_docling(self) -> DoclingParser:
        if self._docling is None:
            self._docling = DoclingParser()
        return self._docling

    def _get_qwen(self) -> QwenParser:
        if self._qwen is None:
            self._qwen = QwenParser()
        return self._qwen

    def parse(
        self,
        info: FileTypeInfo,
        force_qwen_for_pdf: bool = False,
        progress: Callable[[int, int], None] | None = None,
    ) -> ParseResult:
        path = info.path
        fmt = info.format

        if fmt in {DocumentFormat.MARKDOWN, DocumentFormat.TEXT}:
            return self._passthrough(path)

        if fmt == DocumentFormat.IMAGE:
            return self._via_qwen_image(path)

        if fmt == DocumentFormat.PDF:
            return self._handle_pdf(
                path,
                force_qwen=force_qwen_for_pdf,
                progress=progress,
            )

        if fmt in {
            DocumentFormat.DOCX,
            DocumentFormat.PPTX,
            DocumentFormat.XLSX,
            DocumentFormat.HTML,
            DocumentFormat.CSV,
        }:
            return self._via_docling(path)

        raise ValueError(f"No parser configured for format: {fmt.value}")

    # ---- per-strategy implementations ----------------------------------

    def _passthrough(self, path: Path) -> ParseResult:
        text = path.read_text(encoding="utf-8", errors="replace")
        logger.info(f"Passthrough: {path.name} ({len(text)} chars)")
        return ParseResult(markdown=text, parser="passthrough")

    def _via_docling(self, path: Path) -> ParseResult:
        markdown = self._get_docling().parse(path)
        return ParseResult(markdown=markdown, parser="docling")

    def _via_qwen_image(self, path: Path) -> ParseResult:
        markdown = self._get_qwen().extract_image(path)
        return ParseResult(markdown=markdown, parser="qwen3-vl", pages=1)

    def _handle_pdf(
        self,
        path: Path,
        force_qwen: bool,
        progress: Callable[[int, int], None] | None,
    ) -> ParseResult:
        use_qwen = force_qwen or is_scanned_pdf(path)

        if not use_qwen:
            return self._via_docling(path)

        # Try Qwen; if it isn't configured fall back to Docling so the user
        # still gets something useful instead of a hard failure.
        try:
            qwen = self._get_qwen()
        except QwenParserError as exc:
            logger.warning(
                f"Qwen unavailable ({exc}), falling back to Docling for {path.name}"
            )
            return self._via_docling(path)

        markdown = qwen.extract_pdf_pages(path, progress=progress)
        n_pages = markdown.count("<!-- page ") if markdown else 0
        return ParseResult(markdown=markdown, parser="qwen3-vl", pages=n_pages)
