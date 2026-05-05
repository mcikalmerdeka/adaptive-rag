"""Utility modules (PDF inspection, helpers)."""

from .pdf_inspector import (
    PdfInspectionError,
    is_scanned_pdf,
    iter_pdf_page_pngs,
    pdf_page_count,
)

__all__ = [
    "PdfInspectionError",
    "is_scanned_pdf",
    "iter_pdf_page_pngs",
    "pdf_page_count",
]
