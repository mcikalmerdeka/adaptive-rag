"""File type detection module for the document converter system.

This module is responsible for detecting and validating file types
before passing them to the document converter.
"""

from __future__ import annotations

import mimetypes
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class DocumentFormat(Enum):
    """Enumeration of supported document formats."""

    PDF = "pdf"
    DOCX = "docx"
    PPTX = "pptx"
    XLSX = "xlsx"
    HTML = "html"
    MARKDOWN = "md"
    IMAGE = "image"
    CSV = "csv"
    ASCIIDOC = "asciidoc"
    LATEX = "latex"
    XML = "xml"
    JSON = "json"
    AUDIO = "audio"
    VTT = "vtt"
    UNKNOWN = "unknown"


@dataclass
class FileTypeInfo:
    """Information about a detected file type."""

    path: Path
    extension: str
    mime_type: str | None
    format: DocumentFormat
    is_supported: bool


class FileTypeDetector:
    """Detects and validates file types for document conversion.

    This is the first step in the intelligent document processing pipeline.
    It ensures only supported formats are passed to the converter.
    """

    # Mapping of file extensions to DocumentFormat
    EXTENSION_MAP: dict[str, DocumentFormat] = {
        # PDF
        ".pdf": DocumentFormat.PDF,
        # Microsoft Office
        ".docx": DocumentFormat.DOCX,
        ".dotx": DocumentFormat.DOCX,
        ".docm": DocumentFormat.DOCX,
        ".dotm": DocumentFormat.DOCX,
        ".pptx": DocumentFormat.PPTX,
        ".potx": DocumentFormat.PPTX,
        ".ppsx": DocumentFormat.PPTX,
        ".pptm": DocumentFormat.PPTX,
        ".potm": DocumentFormat.PPTX,
        ".ppsm": DocumentFormat.PPTX,
        ".xlsx": DocumentFormat.XLSX,
        ".xlsm": DocumentFormat.XLSX,
        # Web
        ".html": DocumentFormat.HTML,
        ".htm": DocumentFormat.HTML,
        ".xhtml": DocumentFormat.HTML,
        # Markdown
        ".md": DocumentFormat.MARKDOWN,
        ".markdown": DocumentFormat.MARKDOWN,
        # Images
        ".png": DocumentFormat.IMAGE,
        ".jpg": DocumentFormat.IMAGE,
        ".jpeg": DocumentFormat.IMAGE,
        ".tif": DocumentFormat.IMAGE,
        ".tiff": DocumentFormat.IMAGE,
        ".bmp": DocumentFormat.IMAGE,
        ".webp": DocumentFormat.IMAGE,
        # Data
        ".csv": DocumentFormat.CSV,
        # AsciiDoc
        ".adoc": DocumentFormat.ASCIIDOC,
        ".asciidoc": DocumentFormat.ASCIIDOC,
        ".asc": DocumentFormat.ASCIIDOC,
        # LaTeX
        ".tex": DocumentFormat.LATEX,
        # XML
        ".xml": DocumentFormat.XML,
        ".nxml": DocumentFormat.XML,
        # JSON
        ".json": DocumentFormat.JSON,
        # Audio/Video (requires extra dependencies)
        ".wav": DocumentFormat.AUDIO,
        ".mp3": DocumentFormat.AUDIO,
        ".m4a": DocumentFormat.AUDIO,
        ".aac": DocumentFormat.AUDIO,
        ".ogg": DocumentFormat.AUDIO,
        ".flac": DocumentFormat.AUDIO,
        ".mp4": DocumentFormat.AUDIO,
        ".avi": DocumentFormat.AUDIO,
        ".mov": DocumentFormat.AUDIO,
        # WebVTT
        ".vtt": DocumentFormat.VTT,
    }

    # Formats supported by the core converter (docling base install)
    CORE_SUPPORTED_FORMATS: set[DocumentFormat] = {
        DocumentFormat.PDF,
        DocumentFormat.DOCX,
        DocumentFormat.PPTX,
        DocumentFormat.XLSX,
        DocumentFormat.HTML,
        DocumentFormat.MARKDOWN,
        DocumentFormat.IMAGE,
        DocumentFormat.CSV,
        DocumentFormat.ASCIIDOC,
        DocumentFormat.XML,
        DocumentFormat.JSON,
    }

    def __init__(self, allow_audio: bool = False) -> None:
        """Initialize the file type detector.

        Args:
            allow_audio: Whether to allow audio/video formats (requires extra dependencies).
        """
        self.allow_audio = allow_audio
        self._supported_formats = set(self.CORE_SUPPORTED_FORMATS)
        if allow_audio:
            self._supported_formats.add(DocumentFormat.AUDIO)
            self._supported_formats.add(DocumentFormat.VTT)

    def detect(self, file_path: str | Path) -> FileTypeInfo:
        """Detect the file type and return information about it.

        Args:
            file_path: Path to the file to detect.

        Returns:
            FileTypeInfo with detection results.
        """
        path = Path(file_path)
        extension = path.suffix.lower()
        mime_type, _ = mimetypes.guess_type(str(path))

        doc_format = self.EXTENSION_MAP.get(extension, DocumentFormat.UNKNOWN)
        is_supported = doc_format in self._supported_formats

        return FileTypeInfo(
            path=path,
            extension=extension,
            mime_type=mime_type,
            format=doc_format,
            is_supported=is_supported,
        )

    def validate(self, file_path: str | Path) -> FileTypeInfo:
        """Validate that a file is supported for conversion.

        Args:
            file_path: Path to the file to validate.

        Returns:
            FileTypeInfo if the file is supported.

        Raises:
            ValueError: If the file format is not supported.
            FileNotFoundError: If the file does not exist.
        """
        path = Path(file_path)

        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")

        info = self.detect(path)

        if not info.is_supported:
            supported_exts = [
                ext
                for ext, fmt in self.EXTENSION_MAP.items()
                if fmt in self._supported_formats
            ]
            raise ValueError(
                f"Unsupported file format: {info.extension}\n"
                f"Detected format: {info.format.value}\n"
                f"Supported extensions: {', '.join(sorted(set(supported_exts)))}"
            )

        return info

    @property
    def supported_extensions(self) -> list[str]:
        """Return a list of supported file extensions."""
        return sorted(
            {
                ext
                for ext, fmt in self.EXTENSION_MAP.items()
                if fmt in self._supported_formats
            }
        )

    @property
    def supported_formats_text(self) -> str:
        """Return a human-readable description of supported formats."""
        formats = {}
        for ext, fmt in self.EXTENSION_MAP.items():
            if fmt in self._supported_formats:
                formats.setdefault(fmt.value, []).append(ext)

        lines = []
        for fmt_name in sorted(formats.keys()):
            exts = ", ".join(sorted(formats[fmt_name]))
            lines.append(f"- {fmt_name.upper()}: {exts}")

        return "\n".join(lines)
