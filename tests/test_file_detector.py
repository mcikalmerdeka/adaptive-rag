"""Tests for src.core.file_detector — extension mapping, support validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.core.file_detector import DocumentFormat, FileTypeDetector, FileTypeInfo


class TestFileTypeDetector:
    """Map extensions to formats and validate support."""

    def _detector(self) -> FileTypeDetector:
        return FileTypeDetector()

    @pytest.mark.parametrize(
        "ext,expected",
        [
            (".pdf", DocumentFormat.PDF),
            (".docx", DocumentFormat.DOCX),
            (".pptx", DocumentFormat.PPTX),
            (".xlsx", DocumentFormat.XLSX),
            (".html", DocumentFormat.HTML),
            (".htm", DocumentFormat.HTML),
            (".md", DocumentFormat.MARKDOWN),
            (".txt", DocumentFormat.TEXT),
            (".csv", DocumentFormat.CSV),
            (".png", DocumentFormat.IMAGE),
            (".jpg", DocumentFormat.IMAGE),
            (".jpeg", DocumentFormat.IMAGE),
            (".webp", DocumentFormat.IMAGE),
        ],
    )
    def test_known_extensions(self, ext: str, expected: DocumentFormat) -> None:
        d = self._detector()
        info = d.detect(f"file{ext}")
        assert info.format == expected
        assert info.is_supported is True

    def test_unknown_extension(self) -> None:
        d = self._detector()
        info = d.detect("file.xyz")
        assert info.format == DocumentFormat.UNKNOWN
        assert info.is_supported is False

    def test_no_extension(self) -> None:
        d = self._detector()
        info = d.detect("README")
        assert info.format == DocumentFormat.UNKNOWN
        assert info.is_supported is False

    def test_case_insensitive(self) -> None:
        d = self._detector()
        info = d.detect("file.PDF")
        assert info.format == DocumentFormat.PDF
        assert info.is_supported is True

    def test_detect_returns_path_object(self, tmp_path: Path) -> None:
        d = self._detector()
        info = d.detect(tmp_path / "test.pdf")
        assert isinstance(info.path, Path)
        assert info.extension == ".pdf"

    def test_validate_existing_supported(self, tmp_path: Path) -> None:
        f = tmp_path / "doc.txt"
        f.write_text("hello")
        d = self._detector()
        info = d.validate(f)
        assert info.format == DocumentFormat.TEXT
        assert info.is_supported is True

    def test_validate_missing_file(self, tmp_path: Path) -> None:
        d = self._detector()
        with pytest.raises(FileNotFoundError):
            d.validate(tmp_path / "missing.pdf")

    def test_validate_unsupported_format(self, tmp_path: Path) -> None:
        f = tmp_path / "script.py"
        f.write_text("print()")
        d = self._detector()
        with pytest.raises(ValueError) as exc_info:
            d.validate(f)
        assert ".py" in str(exc_info.value)

    def test_supported_extensions_list(self) -> None:
        d = self._detector()
        exts = d.supported_extensions
        assert ".pdf" in exts
        assert ".txt" in exts
        assert ".png" in exts
        assert ".py" not in exts
        assert sorted(exts) == exts  # sorted

    def test_supported_formats_text(self) -> None:
        d = self._detector()
        text = d.supported_formats_text
        assert "PDF" in text.upper()
        assert "IMAGE" in text.upper()
        assert ".pdf" in text
        assert ".png" in text
