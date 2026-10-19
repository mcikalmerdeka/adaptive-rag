"""Tests for src.ui.admin_ui — SQL schema-browser formatting, no Gradio rendering."""

from __future__ import annotations

from unittest.mock import MagicMock

from src.ui.admin_ui import _format_schema


class TestFormatSchema:
    """``_format_schema`` renders the SQL schema browser markdown."""

    def test_none_tool_shows_setup_hint(self) -> None:
        md = _format_schema(None)
        assert "SQL_DATABASE_URL" in md

    def test_error_tool_shows_reason(self) -> None:
        tool = MagicMock()
        tool.describe_schema.return_value = {"error": "connection refused"}
        md = _format_schema(tool)
        assert "connection refused" in md

    def test_renders_database_and_tables(self) -> None:
        tool = MagicMock()
        tool.describe_schema.return_value = {
            "database": "neondb",
            "tables": [
                {
                    "name": "orders",
                    "columns": [
                        {"name": "id", "type": "INTEGER", "nullable": False},
                        {"name": "title", "type": "VARCHAR(100)", "nullable": True},
                    ],
                },
            ],
        }
        md = _format_schema(tool)
        assert "neondb" in md
        assert "orders" in md
        assert "id" in md
        assert "INTEGER" in md
        assert "title" in md
        assert "VARCHAR(100)" in md
        assert "YES" in md and "NO" in md  # nullable flags rendered
