"""Document converter module using Docling.

This module wraps Docling's DocumentConverter to provide a clean interface
for converting various document formats to Markdown.
"""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path

# Fix Windows symlink privilege error when downloading Docling models
# Hugging Face Hub tries to create symlinks by default, which requires
# admin rights or Developer Mode on Windows. Disabling symlinks forces
# copies instead, avoiding WinError 1314.
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS", "1")

from docling.datamodel.base_models import InputFormat
from docling.datamodel.document import ConversionResult
from docling.document_converter import DocumentConverter

from .file_detector import FileTypeDetector, FileTypeInfo

logger = logging.getLogger(__name__)


class DocumentConverterError(Exception):
    """Raised when document conversion fails."""

    pass


class MarkdownConverterService:
    """Service for converting documents to Markdown using Docling.

    This is the core component of the document processing pipeline.
    It handles conversion of multiple file formats to clean Markdown.
    """

    def __init__(self) -> None:
        """Initialize the converter service with Docling."""
        self._detector = FileTypeDetector()
        self._converter = DocumentConverter()
        logger.info("DocumentConverterService initialized with Docling")

    @property
    def detector(self) -> FileTypeDetector:
        """Access the file type detector."""
        return self._detector

    def convert(self, file_path: str | Path) -> str:
        """Convert a document to Markdown.

        Args:
            file_path: Path to the document file.

        Returns:
            The document content as Markdown string.

        Raises:
            DocumentConverterError: If conversion fails.
            ValueError: If file format is not supported.
            FileNotFoundError: If file does not exist.
        """
        file_path = Path(file_path)

        # Step 1: Validate file type
        try:
            file_info = self._detector.validate(file_path)
            logger.info(
                f"Converting {file_info.path.name} "
                f"(format: {file_info.format.value})"
            )
        except (ValueError, FileNotFoundError):
            raise

        # Step 2: Convert using Docling
        try:
            result: ConversionResult = self._converter.convert(str(file_path))

            if result.status.name != "SUCCESS":
                raise DocumentConverterError(
                    f"Conversion failed with status: {result.status.name}"
                )

            # Step 3: Export to Markdown
            markdown_content = result.document.export_to_markdown()

            if not markdown_content or not markdown_content.strip():
                logger.warning(f"Document produced empty markdown: {file_path.name}")
                return ""

            logger.info(
                f"Successfully converted {file_path.name} "
                f"({len(markdown_content)} characters)"
            )
            return markdown_content

        except DocumentConverterError:
            raise
        except Exception as e:
            logger.exception(f"Unexpected error converting {file_path.name}")
            raise DocumentConverterError(
                f"Failed to convert {file_path.name}: {str(e)}"
            ) from e

    def convert_and_save(
        self,
        file_path: str | Path,
        output_path: str | Path | None = None,
    ) -> Path:
        """Convert a document and save the Markdown to a file.

        Args:
            file_path: Path to the document file.
            output_path: Optional output path. If not provided, a temporary file
                        is created with the same name but .md extension.

        Returns:
            Path to the saved Markdown file.
        """
        markdown_content = self.convert(file_path)

        if output_path is None:
            # Create a temp file with the same stem but .md extension
            input_path = Path(file_path)
            output_path = Path(tempfile.gettempdir()) / f"{input_path.stem}.md"

        output_path = Path(output_path)
        output_path.write_text(markdown_content, encoding="utf-8")
        logger.info(f"Markdown saved to: {output_path}")

        return output_path

    def get_file_info(self, file_path: str | Path) -> FileTypeInfo:
        """Get information about a file without converting it.

        Args:
            file_path: Path to the file.

        Returns:
            FileTypeInfo with detection results.
        """
        return self._detector.detect(file_path)

    @property
    def supported_formats(self) -> list[str]:
        """Return list of supported file extensions."""
        return self._detector.supported_extensions
