"""Tests for src.tools.sql_tool — regex safety guards and static helpers.

These tests exercise the ``_clean``, ``_validate`` and ``_inject_limit``
methods without needing a real database connection.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.tools.sql_tool import (
    _FORBIDDEN_KEYWORDS,
    _LIMIT_PATTERN,
    _MULTI_STATEMENT,
    _SELECT_PATTERN,
    SqlTool,
    SqlToolError,
)


# ---------------------------------------------------------------------------
# _clean
# ---------------------------------------------------------------------------


class TestClean:
    """``_clean`` normalises LLM output: fences, language tags, semicolons."""

    def test_strips_markdown_fence(self) -> None:
        raw = "```\nSELECT 1\n```"
        assert SqlTool._clean(raw) == "SELECT 1"

    def test_strips_sql_language_tag(self) -> None:
        raw = "```sql\nSELECT 1\n```"
        assert SqlTool._clean(raw) == "SELECT 1"

    def test_removes_trailing_semicolon(self) -> None:
        assert SqlTool._clean("SELECT 1;") == "SELECT 1"

    def test_noop_on_clean_input(self) -> None:
        assert SqlTool._clean("SELECT 1") == "SELECT 1"

    def test_strips_leading_whitespace(self) -> None:
        assert SqlTool._clean("   SELECT 1   ") == "SELECT 1"

    def test_empty_string(self) -> None:
        assert SqlTool._clean("") == ""

    def test_none_coerces_to_empty(self) -> None:
        assert SqlTool._clean(None) == ""  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# _validate — allowlist / forbidden-keyword guards
# ---------------------------------------------------------------------------


class TestValidate:
    """``_validate`` rejects anything that isn't a safe read-only statement."""

    def test_accepts_select(self) -> None:
        SqlTool._validate("SELECT * FROM customers")

    def test_accepts_with_cte(self) -> None:
        SqlTool._validate("WITH t AS (SELECT 1) SELECT * FROM t")

    def test_rejects_empty(self) -> None:
        with pytest.raises(SqlToolError) as exc:
            SqlTool._validate("")
        assert "Empty SQL" in str(exc.value)

    def test_rejects_insert(self) -> None:
        with pytest.raises(SqlToolError) as exc:
            SqlTool._validate("INSERT INTO t VALUES (1)")
        assert "Only SELECT" in str(exc.value)

    def test_rejects_update(self) -> None:
        with pytest.raises(SqlToolError):
            SqlTool._validate("UPDATE t SET x = 1")

    def test_rejects_delete(self) -> None:
        with pytest.raises(SqlToolError):
            SqlTool._validate("DELETE FROM t")

    def test_rejects_drop(self) -> None:
        with pytest.raises(SqlToolError):
            SqlTool._validate("DROP TABLE t")

    def test_rejects_alter(self) -> None:
        with pytest.raises(SqlToolError):
            SqlTool._validate("ALTER TABLE t ADD COLUMN x INT")

    def test_rejects_create(self) -> None:
        with pytest.raises(SqlToolError):
            SqlTool._validate("CREATE TABLE t (id INT)")

    def test_rejects_truncate(self) -> None:
        with pytest.raises(SqlToolError):
            SqlTool._validate("TRUNCATE TABLE t")

    def test_rejects_grant(self) -> None:
        with pytest.raises(SqlToolError):
            SqlTool._validate("GRANT SELECT ON t TO user")

    def test_rejects_copy(self) -> None:
        with pytest.raises(SqlToolError):
            SqlTool._validate("COPY t TO '/tmp/out.csv'")

    def test_rejects_multi_statement(self) -> None:
        with pytest.raises(SqlToolError) as exc:
            SqlTool._validate("SELECT 1; DROP TABLE t")
        assert "Multiple statements" in str(exc.value)

    def test_rejects_comment_on(self) -> None:
        with pytest.raises(SqlToolError):
            SqlTool._validate("COMMENT ON TABLE t IS 'desc'")

    def test_rejects_security_definer(self) -> None:
        with pytest.raises(SqlToolError):
            SqlTool._validate("CREATE FUNCTION f() SECURITY DEFINER")

    def test_case_insensitive_forbidden(self) -> None:
        with pytest.raises(SqlToolError):
            SqlTool._validate("insert into t values (1)")

    def test_select_in_string_literal_still_rejected(self) -> None:
        # The regex is intentionally simple (not a full SQL parser) and
        # matches forbidden keywords anywhere in the string. A literal
        # containing "DELETE" still triggers the guard.
        with pytest.raises(SqlToolError):
            SqlTool._validate("SELECT 'DELETE FROM t' AS warning")


# ---------------------------------------------------------------------------
# _inject_limit
# ---------------------------------------------------------------------------


class TestInjectLimit:
    """``_inject_limit`` appends LIMIT when absent."""

    @pytest.fixture
    def sql_tool(self) -> SqlTool:
        # Mock out engine creation and schema introspection so we don't need
        # a real Postgres driver.
        with (
            patch("src.tools.sql_tool.create_engine") as mock_engine,
            patch("src.tools.sql_tool.inspect") as mock_inspect,
        ):
            mock_engine.return_value = MagicMock()
            mock_inspector = MagicMock()
            mock_inspector.get_table_names.return_value = []
            mock_inspect.return_value = mock_inspector
            tool = SqlTool("postgresql://u:p@h/d")
            # Manually set the attributes _inject_limit depends on
            tool.row_limit = 200
            yield tool

    def test_adds_limit(self, sql_tool: SqlTool) -> None:
        result = sql_tool._inject_limit("SELECT * FROM t")
        assert result.endswith("LIMIT 200")

    def test_skips_when_present(self, sql_tool: SqlTool) -> None:
        original = "SELECT * FROM t LIMIT 10"
        result = sql_tool._inject_limit(original)
        assert result == original

    def test_case_insensitive_detection(self, sql_tool: SqlTool) -> None:
        original = "SELECT * FROM t limit 50"
        result = sql_tool._inject_limit(original)
        assert result == original


# ---------------------------------------------------------------------------
# Regex patterns (direct unit tests)
# ---------------------------------------------------------------------------


class TestRegexPatterns:
    """Direct tests for the compiled regex objects."""

    @pytest.mark.parametrize(
        "sql,matches",
        [
            ("SELECT 1", True),
            ("  SELECT 1", True),
            ("WITH t AS (SELECT 1) SELECT 1", True),
            ("INSERT INTO t VALUES (1)", False),
            ("UPDATE t SET x=1", False),
            ("", False),
        ],
    )
    def test_select_pattern(self, sql: str, matches: bool) -> None:
        assert bool(_SELECT_PATTERN.match(sql)) is matches

    @pytest.mark.parametrize(
        "sql,matches",
        [
            ("SELECT * FROM t LIMIT 10", True),
            ("SELECT * FROM t limit 5", True),
            ("SELECT * FROM t", False),
            ("SELECT LIMITLESS FROM t", False),
        ],
    )
    def test_limit_pattern(self, sql: str, matches: bool) -> None:
        assert bool(_LIMIT_PATTERN.search(sql)) is matches

    @pytest.mark.parametrize(
        "sql,matches",
        [
            ("SELECT 1; DROP TABLE t", True),
            ("SELECT 1; SELECT 2", True),
            ("SELECT 1", False),
            # String literals containing ';' are *not* multi-statement,
            # but the simple regex can't distinguish them. The regex
            # intentionally errs on the side of caution.
            ("SELECT ';' FROM t", True),
        ],
    )
    def test_multi_statement_pattern(self, sql: str, matches: bool) -> None:
        assert bool(_MULTI_STATEMENT.search(sql)) is matches

    @pytest.mark.parametrize(
        "keyword",
        [
            "INSERT",
            "UPDATE",
            "DELETE",
            "DROP",
            "ALTER",
            "CREATE",
            "TRUNCATE",
            "GRANT",
            "REVOKE",
            "COPY",
            "VACUUM",
            "ANALYZE",
            "REINDEX",
            "CLUSTER",
        ],
    )
    def test_forbidden_keywords(self, keyword: str) -> None:
        assert _FORBIDDEN_KEYWORDS.search(f"{keyword} something") is not None

    def test_forbidden_comment_on(self) -> None:
        assert _FORBIDDEN_KEYWORDS.search("COMMENT ON TABLE t IS 'x'") is not None

    def test_forbidden_security_definer(self) -> None:
        assert (
            _FORBIDDEN_KEYWORDS.search("CREATE FUNCTION f() SECURITY DEFINER")
            is not None
        )

    def test_forbidden_case_insensitive(self) -> None:
        assert _FORBIDDEN_KEYWORDS.search("insert into t") is not None
