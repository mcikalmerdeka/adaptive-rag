"""External tools the adaptive router can dispatch to.

Currently:

- :class:`SqlTool` — read-only Postgres queries, NL\u2192SQL via the LLM,
  with safety guards (statement classifier, statement_timeout, row LIMIT).
"""

from .sql_tool import SqlTool, SqlToolError, SqlResult

__all__ = ["SqlTool", "SqlToolError", "SqlResult"]
