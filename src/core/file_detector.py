"""File type detection for the document converter.

We deliberately keep the supported set small. Exotic formats (LaTeX, AsciiDoc,
XML/JSON, audio, format variants like ``.dotx`` / ``.docm``) are dropped to
keep the surface honest. Add them back only if a concrete use case appears.
"""

from __future__ import annotations

import mimetypes
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class DocumentFormat(Enum):
    PDF = "pdf"
    DOCX = "docx"
    PPTX = "pptx"
    XLSX = "xlsx"
    HTML = "html"
    MARKDOWN = "md"
    TEXT = "txt"
    CSV = "csv"
    IMAGE = "image"
    UNKNOWN = "unknown"


@dataclass
class FileTypeInfo:
    path: Path
    extension: str
    mime_type: str | None
    format: DocumentFormat
    is_supported: bool


class FileTypeDetector:
    """Map file extensions to ``DocumentFormat`` and validate support."""

    EXTENSION_MAP: dict[str, DocumentFormat] = {
        ".pdf": DocumentFormat.PDF,
        ".docx": DocumentFormat.DOCX,
        ".pptx": DocumentFormat.PPTX,
        ".xlsx": DocumentFormat.XLSX,
        ".html": DocumentFormat.HTML,
        ".htm": DocumentFormat.HTML,
        ".md": DocumentFormat.MARKDOWN,
        ".txt": DocumentFormat.TEXT,
        ".csv": DocumentFormat.CSV,
        ".png": DocumentFormat.IMAGE,
        ".jpg": DocumentFormat.IMAGE,
        ".jpeg": DocumentFormat.IMAGE,
        ".webp": DocumentFormat.IMAGE,
    }

    SUPPORTED_FORMATS: set[DocumentFormat] = {
        DocumentFormat.PDF,
        DocumentFormat.DOCX,
        DocumentFormat.PPTX,
        DocumentFormat.XLSX,
        DocumentFormat.HTML,
        DocumentFormat.MARKDOWN,
        DocumentFormat.TEXT,
        DocumentFormat.CSV,
        DocumentFormat.IMAGE,
    }

    def detect(self, file_path: str | Path) -> FileTypeInfo:
        path = Path(file_path)
        extension = path.suffix.lower()
        mime_type, _ = mimetypes.guess_type(str(path))
        doc_format = self.EXTENSION_MAP.get(extension, DocumentFormat.UNKNOWN)
        return FileTypeInfo(
            path=path,
            extension=extension,
            mime_type=mime_type,
            format=doc_format,
            is_supported=doc_format in self.SUPPORTED_FORMATS,
        )

    def validate(self, file_path: str | Path) -> FileTypeInfo:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")

        info = self.detect(path)
        if not info.is_supported:
            raise ValueError(
                f"Unsupported file format: {info.extension}\n"
                f"Detected format: {info.format.value}\n"
                f"Supported extensions: {', '.join(self.supported_extensions)}"
            )
        return info

    @property
    def supported_extensions(self) -> list[str]:
        return sorted(
            ext
            for ext, fmt in self.EXTENSION_MAP.items()
            if fmt in self.SUPPORTED_FORMATS
        )

    @property
    def supported_formats_text(self) -> str:
        groups: dict[str, list[str]] = {}
        for ext, fmt in self.EXTENSION_MAP.items():
            if fmt in self.SUPPORTED_FORMATS:
                groups.setdefault(fmt.value, []).append(ext)

        return "\n".join(
            f"- **{name.upper()}**: {', '.join(sorted(exts))}"
            for name, exts in sorted(groups.items())
        )
