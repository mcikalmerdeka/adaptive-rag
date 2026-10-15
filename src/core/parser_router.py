"""Routing logic: pick the right parser per file type.

Decision table (spec §3):

    Format              auto (default)        plain                 rendered
    .md / .txt          passthrough           passthrough           passthrough
    .html               markitdown            markitdown            markitdown (degrade note)
    .csv                markitdown            markitdown            markitdown (degrade note)
    .docx/.pptx/.xlsx   markitdown            markitdown            export→PDF → GLM page OCR
    .pdf born-digital   markitdown            markitdown            GLM page OCR
    .pdf scanned        GLM page OCR          markitdown (+warn)    GLM page OCR
    .png/.jpg/.webp     GLM image             GLM image             GLM image
    .mp4/.mkv/.mov      GLM video             GLM video             GLM video

Provenance strings: ``"markitdown"`` | ``"passthrough"`` | the resolved GLM
model code. Images and videos have no plain path, so they use GLM in every
mode; the radio governs documents only.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from . import office_renderer
from .file_detector import DocumentFormat, FileTypeInfo
from .glm_parser import GLMParser, GLMParserError
from .markitdown_parser import MarkItDownParser
from src.utils import is_scanned_pdf

logger = logging.getLogger(__name__)

PARSE_MODES = frozenset({"auto", "plain", "rendered"})

# Page blocks are ``<!-- page N -->`` per GLMParser._format_page_block.
_PAGE_BLOCK_MARKER = "<!-- page "


def validate_parse_mode(parse_mode: str) -> str:
    """Return the validated mode or raise ValueError naming the options."""
    if parse_mode not in PARSE_MODES:
        raise ValueError(
            f"parse_mode must be one of {sorted(PARSE_MODES)} (got: {parse_mode!r})"
        )
    return parse_mode


@dataclass
class ParseResult:
    markdown: str
    parser: str  # "markitdown" | "passthrough" | the vision model code
    pages: int | None = None  # only set for page-OCR paths


class ParserRouter:
    """Dispatch a file to the appropriate parser based on type, mode + content."""

    def __init__(
        self,
        markitdown: MarkItDownParser | None = None,
        glm: GLMParser | None = None,
    ) -> None:
        self._markitdown = markitdown
        self._glm = glm

    # Lazy init so we don't pay startup cost for parsers we may never use.

    def _get_markitdown(self) -> MarkItDownParser:
        if self._markitdown is None:
            self._markitdown = MarkItDownParser()
        return self._markitdown

    def _get_glm(self) -> GLMParser:
        if self._glm is None:
            self._glm = GLMParser()
        return self._glm

    def parse(
        self,
        info: FileTypeInfo,
        parse_mode: str = "auto",
        progress: Callable[[int, int], None] | None = None,
    ) -> ParseResult:
        mode = validate_parse_mode(parse_mode)
        path = info.path
        fmt = info.format

        if fmt in {DocumentFormat.MARKDOWN, DocumentFormat.TEXT}:
            return self._passthrough(path)

        if fmt == DocumentFormat.IMAGE:
            return self._via_glm_image(path)

        if fmt == DocumentFormat.VIDEO:
            return self._via_glm_video(path)

        if fmt == DocumentFormat.PDF:
            return self._handle_pdf(path, mode, progress)

        if fmt in {DocumentFormat.DOCX, DocumentFormat.PPTX, DocumentFormat.XLSX}:
            if mode == "rendered":
                return self._via_glm_rendered(path, progress)
            return self._via_markitdown(path)

        if fmt in {DocumentFormat.HTML, DocumentFormat.CSV}:
            if mode == "rendered":
                logger.info(
                    f"rendered mode not applicable for {path.suffix or fmt.value}, "
                    f"falling back to plain for {path.name}"
                )
            return self._via_markitdown(path)

        raise ValueError(f"No parser configured for format: {fmt.value}")

    # ---- per-strategy implementations ----------------------------------

    def _passthrough(self, path: Path) -> ParseResult:
        text = path.read_text(encoding="utf-8", errors="replace")
        logger.info(f"Passthrough: {path.name} ({len(text)} chars)")
        return ParseResult(markdown=text, parser="passthrough")

    def _via_markitdown(self, path: Path) -> ParseResult:
        markdown = self._get_markitdown().parse(path)
        return ParseResult(markdown=markdown, parser="markitdown")

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
        mode: Literal["auto", "plain", "rendered"],
        progress: Callable[[int, int], None] | None,
    ) -> ParseResult:
        scanned = is_scanned_pdf(path)

        if mode == "plain":
            if scanned:
                logger.warning(
                    f"{path.name} looks scanned; plain MarkItDown will only "
                    f"see the text layer (usually near-empty). Use rendered "
                    f"mode for vision OCR."
                )
            return self._via_markitdown(path)

        if mode == "auto" and not scanned:
            return self._via_markitdown(path)

        # Vision OCR: rendered mode, or auto mode with a scanned file.
        try:
            glm = self._get_glm()
        except GLMParserError as exc:
            if mode == "rendered":
                # Explicit opt-in fails loudly — no silent downgrade.
                raise
            logger.warning(
                f"GLM unavailable ({exc}), falling back to plain MarkItDown "
                f"for {path.name}"
            )
            return self._via_markitdown(path)

        return self._via_glm_pdf(path, glm, progress)

    # ---- rendered glue ---------------------------------------------------

    def _via_glm_rendered(
        self,
        path: Path,
        progress: Callable[[int, int], None] | None,
    ) -> ParseResult:
        # Fail fast on a missing API key BEFORE paying for the export.
        glm = self._get_glm()
        pdf_path = office_renderer.to_pdf(path)
        return self._via_glm_pdf(pdf_path, glm, progress)

    def _via_glm_pdf(
        self,
        pdf_path: Path,
        glm: GLMParser,
        progress: Callable[[int, int], None] | None,
    ) -> ParseResult:
        markdown = glm.extract_pdf_pages(pdf_path, progress=progress)
        n_pages = markdown.count(_PAGE_BLOCK_MARKER)
        return ParseResult(
            markdown=markdown,
            parser=glm.model_name,
            pages=n_pages or None,
        )
