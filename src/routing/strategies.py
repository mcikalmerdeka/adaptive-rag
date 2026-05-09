"""The five execution strategies the router picks from.

Keep this enum in lock-step with the descriptions in
:mod:`src.routing.prompts` and the dispatcher in
:mod:`src.routing.dispatcher`.
"""

from __future__ import annotations

from enum import StrEnum


class Strategy(StrEnum):
    NO_RETRIEVAL = "no_retrieval"
    """Greetings / chitchat / generic knowledge / math.
    LLM answers from its own knowledge. No retrieval, no SQL.
    Cheapest path."""

    VECTOR_ONLY = "vector_only"
    """Conceptual / definitional / "what does our policy say" questions.
    Hybrid retrieval over the document index, reranker, grounded LLM
    answer with citations. Default for most prose questions."""

    SQL_ONLY = "sql_only"
    """Quantitative / aggregate questions ("how many", "what's the total",
    "list the top N"). NL\u2192SQL on the warehouse, then LLM summarizes the
    rows in plain language."""

    HYBRID = "hybrid"
    """Question needs both narrative context AND a number. Run vector
    retrieval AND SQL, then combine in synthesis."""

    CLARIFY = "clarify"
    """Question is too ambiguous to answer well. Ask the user a follow-up
    instead of guessing. No retrieval cost on this path either."""


# A short, human-readable handle for UI surfaces.
STRATEGY_LABELS: dict[Strategy, str] = {
    Strategy.NO_RETRIEVAL: "no retrieval",
    Strategy.VECTOR_ONLY: "vector",
    Strategy.SQL_ONLY: "sql",
    Strategy.HYBRID: "hybrid (vector + sql)",
    Strategy.CLARIFY: "clarify",
}


# Strategies that require the SQL backend to be configured.
SQL_STRATEGIES: frozenset[Strategy] = frozenset({Strategy.SQL_ONLY, Strategy.HYBRID})

# Strategies that touch the vector index.
VECTOR_STRATEGIES: frozenset[Strategy] = frozenset(
    {Strategy.VECTOR_ONLY, Strategy.HYBRID}
)
