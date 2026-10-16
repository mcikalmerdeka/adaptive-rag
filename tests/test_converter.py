"""Tests for src.core.converter — service-level parse_mode plumbing."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.core import MarkdownConverterService


def test_bad_parse_mode_raises_eagerly(tmp_path):
    path = tmp_path / "doc.csv"
    path.write_text("name,qty\nwidget,3\n", encoding="utf-8")
    service = MarkdownConverterService()
    with pytest.raises(ValueError, match="parse_mode"):
        service.convert_detailed(path, parse_mode="turbo")


def test_csv_end_to_end(tmp_path):
    path = tmp_path / "doc.csv"
    path.write_text("name,qty\nwidget,3\n", encoding="utf-8")
    service = MarkdownConverterService()

    output = service.convert_detailed(path, parse_mode="plain")

    assert "|" in output.markdown
    assert "widget" in output.markdown
    assert output.parser == "markitdown"
    assert output.pages is None
    assert output.file_info.format.value == "csv"
