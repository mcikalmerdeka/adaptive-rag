"""Read-only SQL tool.

Three jobs:

1. **Introspect the schema once at startup** so the LLM has table /
   column types in its prompt without us hand-maintaining a catalog.
2. **Translate a natural-language intent into a single ``SELECT``** via
   ``ChatOpenAI`` with structured output. Refuses anything that isn't a
   read query.
3. **Execute the SQL safely.** Defense in depth:
   - The DB connection should already be a read-only role
     (``adaptive_rag_ro`` in our seed script).
   - Statement-level allowlist: only ``SELECT`` / ``WITH`` allowed.
   - ``statement_timeout`` set per-session so runaway queries die fast.
   - A ``LIMIT N`` is appended if the SQL doesn't already have one, so
     accidentally returning a million rows can't OOM the UI.

This is intentionally a thin tool — it is *not* an agent. The dispatcher
calls it once with a NL intent, and we either return rows or raise.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from src.config import settings

logger = logging.getLogger(__name__)


# Single-statement, must start with SELECT or WITH (CTEs that resolve to a
# SELECT). Reject anything that smells like a write or DDL even if it would
# also be blocked by the read-only role — defense in depth, and surfaces
# better error messages than letting Postgres reject mid-query.
_SELECT_PATTERN = re.compile(r"^\s*(?:WITH\b|SELECT\b)", re.IGNORECASE)
_FORBIDDEN_KEYWORDS = re.compile(
    r"\b(?:INSERT|UPDATE|DELETE|MERGE|TRUNCATE|DROP|ALTER|CREATE|"
    r"GRANT|REVOKE|COPY|VACUUM|ANALYZE|REINDEX|CLUSTER|"
    r"COMMENT\s+ON|SECURITY\s+DEFINER|DO\s+\$\$)\b",
    re.IGNORECASE,
)
_LIMIT_PATTERN = re.compile(r"\blimit\s+\d+\b", re.IGNORECASE)
_MULTI_STATEMENT = re.compile(r";\s*\S")


SQL_SYSTEM_PROMPT = """You translate natural-language data questions into a
single read-only PostgreSQL SELECT query.

Hard rules:
- Output exactly one statement.
- The statement MUST start with SELECT or WITH.
- NEVER write, modify or define schema (no INSERT, UPDATE, DELETE, CREATE,
  DROP, ALTER, etc.). The connection is read-only and will reject them
  anyway, but don't generate them.
- Use only the tables and columns shown in the schema below.
- When the question implies a time window like "last month" or "this year",
  prefer ``WHERE col >= NOW() - INTERVAL 'N units'`` over hardcoded dates.
- Add an explicit ORDER BY when the question implies ranking ("top",
  "most", "biggest").
- If the question is ambiguous or cannot be answered from this schema,
  return a single SELECT that explains the gap, e.g.
  ``SELECT 'cannot answer: <reason>' AS error;``
- Output only the SQL — no commentary, no markdown fences.
"""

SQL_USER_TEMPLATE = """Schema:

{schema}

Question:
{intent}
"""


class _SqlOutput(BaseModel):
    """Structured output the SQL LLM is forced into."""

    sql: str = Field(
        ...,
        description=(
            "A single PostgreSQL SELECT statement that answers the question. "
            "No trailing semicolon, no markdown fences."
        ),
    )


class SqlToolError(Exception):
    """Raised when the SQL tool can't produce or execute a safe query."""


@dataclass
class SqlResult:
    """One execution of one query."""

    intent: str
    sql: str
    columns: list[str] = field(default_factory=list)
    rows: list[dict[str, Any]] = field(default_factory=list)
    truncated: bool = False
    elapsed_ms: float = 0.0

    @property
    def row_count(self) -> int:
        return len(self.rows)


class SqlTool:
    """Schema-aware NL\u2192SQL tool with read-only execution."""

    def __init__(
        self,
        database_url: str | None = None,
        *,
        statement_timeout_sec: int | None = None,
        row_limit: int | None = None,
        translator_model: str | None = None,
    ) -> None:
        url = database_url or settings.SQL_DATABASE_URL
        if not url:
            raise SqlToolError(
                "SQL_DATABASE_URL is not set. The SQL tool needs a connection "
                "string. Run scripts/seed_demo_data.py first or point at your "
                "own Postgres."
            )

        self.database_url = url
        self.statement_timeout_sec = (
            statement_timeout_sec or settings.SQL_QUERY_TIMEOUT_SEC
        )
        self.row_limit = row_limit or settings.SQL_ROW_LIMIT

        try:
            self._engine: Engine = create_engine(url, future=True, pool_pre_ping=True)
        except SQLAlchemyError as exc:
            raise SqlToolError(f"Cannot create SQL engine: {exc}") from exc

        # Cache the schema description — it doesn't change at runtime and
        # we'd otherwise pay an introspection round-trip on every query.
        self._schema_text = self._describe_schema()

        self._llm = ChatOpenAI(
            model=translator_model or settings.SQL_MODEL,
            temperature=0.0,
            max_tokens=400,
        ).with_structured_output(_SqlOutput)

        logger.info(
            f"SqlTool ready (db={self._safe_url()}, "
            f"timeout={self.statement_timeout_sec}s, row_limit={self.row_limit})"
        )

    # ---- public API ---------------------------------------------------

    @property
    def schema_text(self) -> str:
        """Human-readable schema description (cached)."""
        return self._schema_text

    def schema_summary(self) -> str:
        """One-line-per-table summary, suitable for the router prompt."""
        try:
            inspector = inspect(self._engine)
            lines: list[str] = []
            for table in sorted(inspector.get_table_names(schema="public")):
                cols = [c["name"] for c in inspector.get_columns(table, schema="public")]
                preview = ", ".join(cols[:6])
                if len(cols) > 6:
                    preview += ", \u2026"
                lines.append(f"- {table}: {preview}")
            return "\n".join(lines)
        except SQLAlchemyError as exc:
            logger.warning(f"Schema summary failed: {exc}")
            return "(schema introspection failed)"

    def answer(self, intent: str) -> SqlResult:
        """End-to-end: NL intent -> SQL -> rows."""
        sql = self.translate(intent)
        return self.execute(sql, intent=intent)

    def translate(self, intent: str) -> str:
        """Ask the LLM for a single SELECT statement matching ``intent``."""
        intent = (intent or "").strip()
        if not intent:
            raise SqlToolError("Empty intent — nothing to translate.")

        messages = [
            {"role": "system", "content": SQL_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": SQL_USER_TEMPLATE.format(
                    schema=self._schema_text,
                    intent=intent,
                ),
            },
        ]
        from src.observability import get_callback_handler

        try:
            output: _SqlOutput = self._llm.invoke(
                messages,
                config={
                    "callbacks": get_callback_handler(),
                    "run_name": "sql_tool.translate",
                    "metadata": {"langfuse_tags": ["sql_tool", "nl2sql"]},
                },
            )
        except Exception as exc:
            raise SqlToolError(f"LLM SQL translation failed: {exc}") from exc

        sql = self._clean(output.sql)
        self._validate(sql)
        return sql

    def execute(self, sql: str, *, intent: str = "") -> SqlResult:
        """Validate and run ``sql``, returning a :class:`SqlResult`."""
        sql = self._clean(sql)
        self._validate(sql)
        sql_to_run = self._inject_limit(sql)

        import time
        t0 = time.perf_counter()
        try:
            with self._engine.connect() as conn:
                # Per-session timeout so runaway plans die fast. Postgres
                # accepts an integer string of milliseconds.
                conn.exec_driver_sql(
                    f"SET statement_timeout = {self.statement_timeout_sec * 1000}"
                )
                # Force read-only at the transaction level too. With a RO
                # role this is redundant, but it makes the intent explicit
                # and protects against misconfigured connection strings.
                conn.exec_driver_sql("SET TRANSACTION READ ONLY")
                result = conn.execute(text(sql_to_run))
                rows = result.mappings().all()
                columns = list(result.keys())
        except SQLAlchemyError as exc:
            raise SqlToolError(f"SQL execution failed: {exc}") from exc
        elapsed_ms = (time.perf_counter() - t0) * 1000

        truncated = len(rows) >= self.row_limit and not _LIMIT_PATTERN.search(sql)
        materialised = [dict(r) for r in rows]
        logger.info(
            f"SqlTool.execute: {len(materialised)} rows ({elapsed_ms:.0f}ms) "
            f"truncated={truncated}"
        )
        return SqlResult(
            intent=intent,
            sql=sql,
            columns=columns,
            rows=materialised,
            truncated=truncated,
            elapsed_ms=elapsed_ms,
        )

    # ---- internals ----------------------------------------------------

    @staticmethod
    def _clean(sql: str) -> str:
        sql = (sql or "").strip()
        # Strip surrounding markdown fence in case the LLM ignored the prompt.
        if sql.startswith("```"):
            sql = sql.strip("`")
            # After stripping backticks, drop a leading ``sql`` language tag.
            sql = re.sub(r"^\s*sql\b", "", sql, flags=re.IGNORECASE).strip()
        # Drop single trailing semicolon — we'll add LIMIT before it otherwise.
        sql = sql.rstrip(";").strip()
        return sql

    @staticmethod
    def _validate(sql: str) -> None:
        if not sql:
            raise SqlToolError("Empty SQL produced.")
        if not _SELECT_PATTERN.match(sql):
            raise SqlToolError(
                "Only SELECT / WITH statements are allowed. "
                f"Got: {sql.split()[0] if sql else '?'}\u2026"
            )
        if _MULTI_STATEMENT.search(sql):
            raise SqlToolError("Multiple statements are not allowed.")
        if _FORBIDDEN_KEYWORDS.search(sql):
            raise SqlToolError(
                "SQL contains a forbidden keyword (write / DDL operation)."
            )

    def _inject_limit(self, sql: str) -> str:
        if _LIMIT_PATTERN.search(sql):
            return sql
        return f"{sql}\nLIMIT {self.row_limit}"

    def _safe_url(self) -> str:
        # Hide credentials in log lines.
        url = self.database_url
        if "://" in url and "@" in url:
            scheme, rest = url.split("://", 1)
            creds, host = rest.rsplit("@", 1)
            if ":" in creds:
                user, _ = creds.split(":", 1)
                return f"{scheme}://{user}:****@{host}"
        return url

    def _describe_schema(self) -> str:
        try:
            inspector = inspect(self._engine)
            tables = sorted(inspector.get_table_names(schema="public"))
        except SQLAlchemyError as exc:
            raise SqlToolError(f"Cannot introspect schema: {exc}") from exc

        if not tables:
            return "(no tables found in 'public' schema)"

        chunks: list[str] = []
        for table in tables:
            cols = inspector.get_columns(table, schema="public")
            pk = inspector.get_pk_constraint(table, schema="public").get(
                "constrained_columns", []
            ) or []
            fks = inspector.get_foreign_keys(table, schema="public") or []

            col_lines: list[str] = []
            for c in cols:
                pk_marker = " PRIMARY KEY" if c["name"] in pk else ""
                nullable = "" if c.get("nullable", True) else " NOT NULL"
                col_lines.append(f"    {c['name']} {c['type']}{nullable}{pk_marker}")

            fk_lines: list[str] = []
            for fk in fks:
                local = ", ".join(fk["constrained_columns"])
                remote_table = fk["referred_table"]
                remote_cols = ", ".join(fk["referred_columns"])
                fk_lines.append(f"    FOREIGN KEY ({local}) -> {remote_table}({remote_cols})")

            block = f"TABLE {table} (\n" + ",\n".join(col_lines)
            if fk_lines:
                block += "\n    --\n" + "\n".join(fk_lines)
            block += "\n)"
            chunks.append(block)
        return "\n\n".join(chunks)
