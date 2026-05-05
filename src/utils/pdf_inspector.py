"""PDF inspection utilities.

Two responsibilities:
1. Decide whether a PDF is born-digital (has a real text layer) or scanned (image-only).
2. Render PDF pages to PNG bytes when we need to ship them to a vision model.

Uses ``pypdfium2`` because it is MIT-licensed, has no system dependencies, and
gives us both text extraction and rasterization in one library.
"""

from __future__ import annotations

import io
import logging
from collections.abc import Iterator
from pathlib import Path

import pypdfium2 as pdfium

logger = logging.getLogger(__name__)


class PdfInspectionError(Exception):
    """Raised when a PDF cannot be opened or inspected."""


# Empirically: a born-digital PDF page typically has hundreds to thousands
# of characters in its text layer. A scanned page returns ~0 chars (or just
# a few stray glyphs from embedded annotations). 150 chars across 3 sample
# pages is a comfortable threshold.
_SCANNED_TEXT_THRESHOLD = 150
_SAMPLE_PAGES = 3


def pdf_page_count(path: str | Path) -> int:
    """Return the number of pages in a PDF."""
    path = Path(path)
    try:
        pdf = pdfium.PdfDocument(str(path))
    except Exception as exc:
        raise PdfInspectionError(f"Cannot open PDF {path}: {exc}") from exc
    try:
        return len(pdf)
    finally:
        pdf.close()


def is_scanned_pdf(
    path: str | Path,
    threshold: int = _SCANNED_TEXT_THRESHOLD,
    sample_pages: int = _SAMPLE_PAGES,
) -> bool:
    """Heuristic: return True if the PDF appears to be scanned (image-only).

    Samples the first ``sample_pages`` pages and counts extractable text.
    If the total is below ``threshold``, treats the document as scanned.
    """
    path = Path(path)
    try:
        pdf = pdfium.PdfDocument(str(path))
    except Exception as exc:
        raise PdfInspectionError(f"Cannot open PDF {path}: {exc}") from exc

    try:
        n = min(len(pdf), sample_pages)
        if n == 0:
            return False

        total_chars = 0
        for i in range(n):
            page = pdf[i]
            try:
                text_page = page.get_textpage()
                try:
                    text = text_page.get_text_range() or ""
                finally:
                    text_page.close()
                total_chars += len(text.strip())
            finally:
                page.close()

        scanned = total_chars < threshold
        logger.info(
            f"PDF inspection: {path.name} sampled {n} pages, "
            f"{total_chars} text chars → {'scanned' if scanned else 'born-digital'}"
        )
        return scanned
    finally:
        pdf.close()


def iter_pdf_page_pngs(
    path: str | Path,
    scale: float = 2.0,
) -> Iterator[tuple[int, bytes]]:
    """Yield ``(page_number, png_bytes)`` for each page of a PDF.

    Page numbers are 1-indexed. ``scale=2.0`` ≈ 144 DPI which is a good
    balance between OCR accuracy and request size for VLM APIs.
    """
    path = Path(path)
    try:
        pdf = pdfium.PdfDocument(str(path))
    except Exception as exc:
        raise PdfInspectionError(f"Cannot open PDF {path}: {exc}") from exc

    try:
        for i, page in enumerate(pdf, start=1):
            try:
                bitmap = page.render(scale=scale)
                pil_image = bitmap.to_pil()
                buf = io.BytesIO()
                pil_image.save(buf, format="PNG")
                yield i, buf.getvalue()
            finally:
                page.close()
    finally:
        pdf.close()
