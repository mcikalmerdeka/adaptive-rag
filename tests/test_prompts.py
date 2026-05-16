"""Tests for src.routing.prompts — completeness and placeholder hygiene."""

from __future__ import annotations

import pytest

from src.routing.prompts import (
    FEW_SHOT_EXAMPLES,
    NO_SCHEMA_BLOCK,
    ROUTER_SYSTEM_PROMPT,
    SCHEMA_BLOCK_TEMPLATE,
)


class TestSystemPrompt:
    """The router system prompt mentions every strategy."""

    def test_mentions_all_strategies(self) -> None:
        for value in ("no_retrieval", "vector_only", "sql_only", "hybrid", "clarify"):
            assert value in ROUTER_SYSTEM_PROMPT.lower(), f"Missing strategy: {value}"

    def test_not_empty(self) -> None:
        assert len(ROUTER_SYSTEM_PROMPT) > 500


class TestSchemaBlock:
    """Schema template uses exactly one named placeholder."""

    def test_has_schema_summary_placeholder(self) -> None:
        assert "{schema_summary}" in SCHEMA_BLOCK_TEMPLATE

    def test_no_schema_block_text(self) -> None:
        assert "sql_only or hybrid" in NO_SCHEMA_BLOCK.lower()


class TestFewShotExamples:
    """Few-shot examples cover every strategy at least once."""

    def test_cover_all_strategies(self) -> None:
        strategies_in_examples = set()
        for ex in FEW_SHOT_EXAMPLES:
            assistant = ex["assistant"]
            assert "strategy" in assistant
            strategies_in_examples.add(assistant["strategy"])

        expected = {"no_retrieval", "vector_only", "sql_only", "hybrid", "clarify"}
        assert strategies_in_examples == expected

    def test_examples_have_reasoning(self) -> None:
        for ex in FEW_SHOT_EXAMPLES:
            assistant = ex["assistant"]
            assert "reasoning" in assistant
            assert len(assistant["reasoning"]) > 10

    def test_user_and_assistant_keys(self) -> None:
        for ex in FEW_SHOT_EXAMPLES:
            assert "user" in ex
            assert "assistant" in ex
