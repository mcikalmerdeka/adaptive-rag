"""Tests for src.synthesis.response — message-content flattening.

The Responses API path (taken whenever a `reasoning` dict is set) returns
`AIMessage.content` as a list of typed blocks instead of a plain string;
Chat Completions returns a string. The answerer must handle both.
"""

from __future__ import annotations

from typing import Any

from langchain_core.documents import Document
from langchain_core.messages import AIMessage

import pytest

from src.retrieval import RetrievedChunk
from src.synthesis.response import GroundedAnswerer


class _StubLLM:
    """ChatOpenAI stand-in that returns a canned AIMessage."""

    def __init__(self, message: AIMessage) -> None:
        self._message = message

    def invoke(self, messages: Any, config: Any = None) -> AIMessage:
        return self._message


def _answerer(
    monkeypatch: pytest.MonkeyPatch, message: AIMessage
) -> GroundedAnswerer:
    answerer = GroundedAnswerer()
    monkeypatch.setattr(answerer, "_llm", _StubLLM(message))
    return answerer


class TestContentFlattening:
    def test_answer_direct_extracts_text_from_content_blocks(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        answerer = _answerer(
            monkeypatch,
            AIMessage(content=[{"type": "text", "text": "OK"}]),
        )
        resp = answerer.answer_direct("ping")
        assert resp.answer == "OK"

    def test_answer_direct_keeps_plain_string_content(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        answerer = _answerer(monkeypatch, AIMessage(content="hello there"))
        resp = answerer.answer_direct("ping")
        assert resp.answer == "hello there"

    def test_grounded_extracts_text_from_content_blocks(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        chunk = RetrievedChunk(
            document=Document(
                page_content="The refund window is 30 days.",
                metadata={"filename": "policy.pdf"},
            ),
            hybrid_score=1.0,
        )
        answerer = _answerer(
            monkeypatch,
            AIMessage(content=[{"type": "text", "text": "The window is 30 days. [1]"}]),
        )
        resp = answerer.answer("refund window?", [chunk])
        assert resp.answer == "The window is 30 days. [1]"
        assert resp.cited_indices == [1]
