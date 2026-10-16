"""Tests for src.core.markitdown_parser — the thin MarkItDown wrapper.

The real MarkItDown converter is exercised offline (CSV is pure library
code); LLM-free by design.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from markitdown import DocumentConverterResult, FileConversionException

from src.core.markitdown_parser import MarkItDownParser, MarkItDownParserError


def _make_csv(tmp_path: Path) -> Path:
    p = tmp_path / "tiny.csv"
    p.write_text("name,qty\nwidget,3\n", encoding="utf-8")
    return p


def test_csv_converts_offline(tmp_path):
    md = MarkItDownParser().parse(_make_csv(tmp_path))
    assert isinstance(md, str)
    assert "widget" in md
    assert "|" in md


def test_missing_file_raises_filenotfound(tmp_path):
    parser = MarkItDownParser()
    with pytest.raises(FileNotFoundError):
        parser.parse(tmp_path / "nope.csv")


def test_conversion_exception_wrapped(tmp_path):
    parser = MarkItDownParser()

    def _boom(*args, **kwargs):
        raise FileConversionException("boom")

    parser._converter.convert = _boom
    with pytest.raises(MarkItDownParserError, match="boom"):
        parser.parse(_make_csv(tmp_path))


def test_missing_dependency_wrapped(tmp_path):
    from markitdown import MissingDependencyException

    parser = MarkItDownParser()

    def _gone(*args, **kwargs):
        raise MissingDependencyException("gone")

    parser._converter.convert = _gone
    with pytest.raises(MarkItDownParserError, match="gone"):
        parser.parse(_make_csv(tmp_path))


def test_empty_output_returns_empty_string_and_logs(tmp_path, caplog):
    parser = MarkItDownParser()
    parser._converter.convert = (
        lambda *args, **kwargs: DocumentConverterResult(markdown="")
    )
    with caplog.at_level(logging.WARNING, logger="src.core.markitdown_parser"):
        result = parser.parse(_make_csv(tmp_path))
    assert result == ""
    assert any("empty" in record.message.lower() for record in caplog.records)
