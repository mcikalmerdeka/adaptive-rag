"""Public conversion API.

This is the only thing the UI / external code should need to import. It
ties together file detection, parser routing, and progress reporting into
one stable interface.
"""

from __future__ import annotations

import logging
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .docling_parser import DoclingParserError
from .file_detector import FileTypeDetector, FileTypeInfo
from .parser_router import ParserRouter, ParseResult
from .qwen_parser import QwenParserError

logger = logging.getLogger(__name__)


class DocumentConverterError(Exception):
    """Wraps any failure during conversion (detection, parsing, IO)."""


@dataclass
class ConversionOutput:
    markdown: str
    parser: str
    pages: int | None
    file_info: FileTypeInfo


class MarkdownConverterService:
    """High-level API that the Gradio UI consumes.

    Backward-compatible: ``convert(path) -> str`` still works. New callers
    can use ``convert_detailed`` to get parser provenance and page count.
    """

    def __init__(self) -> None:
        self._detector = FileTypeDetector()
        self._router = ParserRouter()
        logger.info("MarkdownConverterService initialized")

    @property
    def detector(self) -> FileTypeDetector:
        return self._detector

    @property
    def supported_formats(self) -> list[str]:
        return self._detector.supported_extensions

    # ---- detection -----------------------------------------------------

    def get_file_info(self, file_path: str | Path) -> FileTypeInfo:
        return self._detector.detect(file_path)

    # ---- conversion ----------------------------------------------------

    def convert(
        self,
        file_path: str | Path,
        force_qwen_for_pdf: bool = False,
        progress: Callable[[int, int], None] | None = None,
    ) -> str:
        return self.convert_detailed(
            file_path,
            force_qwen_for_pdf=force_qwen_for_pdf,
            progress=progress,
        ).markdown

    def convert_detailed(
        self,
        file_path: str | Path,
        force_qwen_for_pdf: bool = False,
        progress: Callable[[int, int], None] | None = None,
    ) -> ConversionOutput:
        info = self._detector.validate(file_path)
        logger.info(
            f"Converting {info.path.name} (format: {info.format.value})"
        )

        try:
            result: ParseResult = self._router.parse(
                info,
                force_qwen_for_pdf=force_qwen_for_pdf,
                progress=progress,
            )
        except (DoclingParserError, QwenParserError) as exc:
            raise DocumentConverterError(str(exc)) from exc
        except (ValueError, FileNotFoundError):
            raise
        except Exception as exc:
            logger.exception(f"Unexpected failure converting {info.path.name}")
            raise DocumentConverterError(
                f"Failed to convert {info.path.name}: {exc}"
            ) from exc

        if not result.markdown.strip():
            logger.warning(f"Empty markdown output for {info.path.name}")

        return ConversionOutput(
            markdown=result.markdown,
            parser=result.parser,
            pages=result.pages,
            file_info=info,
        )

    def convert_and_save(
        self,
        file_path: str | Path,
        output_path: str | Path | None = None,
        force_qwen_for_pdf: bool = False,
    ) -> Path:
        markdown = self.convert(file_path, force_qwen_for_pdf=force_qwen_for_pdf)
        if output_path is None:
            stem = Path(file_path).stem
            output_path = Path(tempfile.gettempdir()) / f"{stem}.md"
        output_path = Path(output_path)
        output_path.write_text(markdown, encoding="utf-8")
        logger.info(f"Markdown saved to: {output_path}")
        return output_path
