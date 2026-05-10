"""Observability layer.

Currently:

- :mod:`langfuse_client` — singleton Langfuse client + ``CallbackHandler``
  factory + ``is_enabled`` flag. Tracing is a no-op when keys are missing,
  so the rest of the app doesn't need conditional imports.
- :mod:`cost_tracker` — read-side helpers that pull cost / token / latency
  summaries from the Langfuse public API (no separate price table to
  maintain).
"""

from .cost_tracker import CostSummary, DailyMetrics, ModelUsage, fetch_cost_summary
from .langfuse_client import (
    flush_traces,
    get_callback_handler,
    get_langfuse,
    is_langfuse_enabled,
    span,
)

__all__ = [
    "CostSummary",
    "DailyMetrics",
    "ModelUsage",
    "fetch_cost_summary",
    "flush_traces",
    "get_callback_handler",
    "get_langfuse",
    "is_langfuse_enabled",
    "span",
]
