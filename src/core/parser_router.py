"""Routing logic: pick the right parser per file type.

Decision table:

    .md / .txt                                 → passthrough (read file)
    .png / .jpg / .jpeg / .webp                → GLM-5.3-Flash (image OCR)
    .pdf scanned (heuristic)                   → GLM (page-by-page, cached)
    .pdf born-digital                          → Docling
    .mp4 / .mkv / .mov                         → GLM (video understanding)
    .docx / .pptx / .xlsx / .html / .csv       → Docling

A ``force_vlm_for_pdf`` flag lets the UI override the heuristic when the
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
from .glm_parser import GLMParser, GLMParserError

logger = logging.getLogger(__name__)


@dataclass
class ParseResult:
    markdown: str
    parser: str  # "docling" | "passthrough" | the vision model code
    pages: int | None = None  # only set for PDFs


class ParserRouter:
    """Dispatch a file to the appropriate parser based on type + content."""

    def __init__(
        self,
        docling: DoclingParser | None = None,
        glm: GLMParser | None = None,
    ) -> None:
        self._docling = docling
        self._glm = glm

    # Lazy init so we don't pay startup cost for parsers we may never use.

    def _get_docling(self) -> DoclingParser:
        if self._docling is None:
            self._docling = DoclingParser()
        return self._docling

    def _get_glm(self) -> GLMParser:
        if self._glm is None:
            self._glm = GLMParser()
        return self._glm

    def parse(
        self,
        info: FileTypeInfo,
        force_vlm_for_pdf: bool = False,
        progress: Callable[[int, int], None] | None = None,
    ) -> ParseResult:
        path = info.path
        fmt = info.format

        if fmt in {DocumentFormat.MARKDOWN, DocumentFormat.TEXT}:
            return self._passthrough(path)

        if fmt == DocumentFormat.IMAGE:
            return self._via_glm_image(path)

        if fmt == DocumentFormat.VIDEO:
            return self._via_glm_video(path)

        if fmt == DocumentFormat.PDF:
            return self._handle_pdf(
                path,
                force_vlm=force_vlm_for_pdf,
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

    def _via_glm_image(self, path: Path) -> ParseResult:
        glm = self._get_glm()
        markdown = glm.extract_image(path)
        return ParseResult(markdown=markdown, parser=glm.model_name)

    def _via_glm_video(self, path: Path) -> ParseResult:
        try:
            glm = self._get_glm()
        except GLMParserError as exc:
            # No fallback parser can understand video — fail loudly.
            raise ValueError(
                f"Video ingestion requires ZAI_API_KEY. Add it to .env to "
                f"enable video analysis ({exc})"
            ) from exc
        markdown = glm.extract_video(path)
        return ParseResult(markdown=markdown, parser=glm.model_name, pages=None)

    def _handle_pdf(
        self,
        path: Path,
        force_vlm: bool,
        progress: Callable[[int, int], None] | None,
    ) -> ParseResult:
        use_vlm = force_vlm or is_scanned_pdf(path)

        if not use_vlm:
            return self._via_docling(path)

        # Try GLM; if it isn't configured fall back to Docling so the user
        # still gets something useful instead of a hard failure.
        try:
            glm = self._get_glm()
        except GLMParserError as exc:
            logger.warning(
                f"GLM unavailable ({exc}), falling back to Docling for {path.name}"
            )
            return self._via_docling(path)

        markdown = glm.extract_pdf_pages(path, progress=progress)
        n_pages = markdown.count("<!-- page ") if markdown else 0
        return ParseResult(markdown=markdown, parser=glm.model_name, pages=n_pages)
