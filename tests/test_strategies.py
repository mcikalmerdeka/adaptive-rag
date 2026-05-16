"""Tests for src.routing.strategies — enum values, labels, capability sets."""

from __future__ import annotations

import pytest

from src.routing.strategies import (
    SQL_STRATEGIES,
    STRATEGY_LABELS,
    Strategy,
)


class TestStrategyEnum:
    """Strategy is a StrEnum with five members."""

    def test_members(self) -> None:
        assert Strategy.NO_RETRIEVAL == "no_retrieval"
        assert Strategy.VECTOR_ONLY == "vector_only"
        assert Strategy.SQL_ONLY == "sql_only"
        assert Strategy.HYBRID == "hybrid"
        assert Strategy.CLARIFY == "clarify"

    def test_values_match_names(self) -> None:
        for member in Strategy:
            assert member.value == member.value.lower()
            assert member.name.lower().replace("_", "_") == member.name.lower()

    def test_membership(self) -> None:
        assert Strategy.SQL_ONLY in Strategy
        assert Strategy.HYBRID in Strategy
        assert Strategy.NO_RETRIEVAL in Strategy


class TestStrategyLabels:
    """Every strategy has a human-readable label."""

    def test_all_strategies_have_label(self) -> None:
        for strategy in Strategy:
            assert strategy in STRATEGY_LABELS
            assert isinstance(STRATEGY_LABELS[strategy], str)
            assert len(STRATEGY_LABELS[strategy]) > 0

    def test_label_content(self) -> None:
        assert STRATEGY_LABELS[Strategy.NO_RETRIEVAL] == "no retrieval"
        assert STRATEGY_LABELS[Strategy.VECTOR_ONLY] == "vector"
        assert STRATEGY_LABELS[Strategy.SQL_ONLY] == "sql"
        assert STRATEGY_LABELS[Strategy.HYBRID] == "hybrid (vector + sql)"
        assert STRATEGY_LABELS[Strategy.CLARIFY] == "clarify"


class TestSqlStrategies:
    """The SQL_STRATEGIES frozenset correctly identifies DB-dependent strategies."""

    def test_exact_members(self) -> None:
        assert SQL_STRATEGIES == frozenset({Strategy.SQL_ONLY, Strategy.HYBRID})

    @pytest.mark.parametrize(
        "strategy,needs_sql",
        [
            (Strategy.NO_RETRIEVAL, False),
            (Strategy.VECTOR_ONLY, False),
            (Strategy.CLARIFY, False),
            (Strategy.SQL_ONLY, True),
            (Strategy.HYBRID, True),
        ],
    )
    def test_strategy_needs_sql(self, strategy: Strategy, needs_sql: bool) -> None:
        assert (strategy in SQL_STRATEGIES) is needs_sql

    def test_no_extra_members(self) -> None:
        assert len(SQL_STRATEGIES) == 2
