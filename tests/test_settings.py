"""Tests for src.config.settings — env var parsing, defaults, immutability."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from src.config.settings import Settings, _env_float, _env_int, _env_optional, _env_str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class TestEnvHelpers:
    """Unit-test the private env helpers without touching real env vars."""

    def test_env_int_with_value(self) -> None:
        with patch.dict(os.environ, {"TEST_INT": "42"}, clear=False):
            assert _env_int("TEST_INT", 0) == 42

    def test_env_int_missing(self) -> None:
        with patch.dict(os.environ, {"TEST_INT_X": ""}, clear=False):
            assert _env_int("TEST_INT_MISSING", 7) == 7

    def test_env_int_empty_string(self) -> None:
        with patch.dict(os.environ, {"TEST_INT": ""}, clear=False):
            assert _env_int("TEST_INT", 7) == 7

    def test_env_float_with_value(self) -> None:
        with patch.dict(os.environ, {"TEST_FLOAT": "3.14"}, clear=False):
            assert _env_float("TEST_FLOAT", 0.0) == 3.14

    def test_env_float_missing(self) -> None:
        assert _env_float("TEST_FLOAT_MISSING", 1.5) == 1.5

    def test_env_str_with_value(self) -> None:
        with patch.dict(os.environ, {"TEST_STR": "hello"}, clear=False):
            assert _env_str("TEST_STR", "default") == "hello"

    def test_env_str_missing(self) -> None:
        assert _env_str("TEST_STR_MISSING", "default") == "default"

    def test_env_optional_with_value(self) -> None:
        with patch.dict(os.environ, {"TEST_OPT": "present"}, clear=False):
            assert _env_optional("TEST_OPT") == "present"

    def test_env_optional_missing(self) -> None:
        assert _env_optional("TEST_OPT_MISSING") is None

    def test_env_optional_empty_string(self) -> None:
        with patch.dict(os.environ, {"TEST_OPT": ""}, clear=False):
            assert _env_optional("TEST_OPT") is None


# ---------------------------------------------------------------------------
# Settings dataclass
# ---------------------------------------------------------------------------


class TestSettings:
    """Integration-style test for Settings construction."""

    def test_all_defaults(self) -> None:
        """Settings created with nothing but defaults should be valid."""
        s = Settings(
            OPENAI_API_KEY=None,
            QWEN_API_KEY=None,
            QDRANT_URL=None,
            QDRANT_API_KEY=None,
            QDRANT_PATH="./qdrant_storage",
            QDRANT_COLLECTION="adaptive_rag",
            DENSE_MODEL="text-embedding-3-small",
            DENSE_SIZE=1536,
            SPARSE_MODEL="Qdrant/bm25",
            CHUNK_SIZE=1500,
            CHUNK_OVERLAP=200,
            RETRIEVAL_PREFETCH_K=25,
            RERANK_TOP_K=5,
            RERANKER_MODEL="ms-marco-MiniLM-L-12-v2",
            LLM_MODEL="gpt-4.1-mini",
            LLM_TEMPERATURE=0.2,
            LLM_MAX_TOKENS=1024,
            ROUTER_MODEL="gpt-4.1-nano",
            ROUTER_TEMPERATURE=0.0,
            SQL_MODEL="gpt-4.1-mini",
            SQL_DATABASE_URL=None,
            SQL_QUERY_TIMEOUT_SEC=5,
            SQL_ROW_LIMIT=200,
            LANGFUSE_PUBLIC_KEY=None,
            LANGFUSE_SECRET_KEY=None,
            LANGFUSE_HOST="https://cloud.langfuse.com",
            CACHE_DIR=Path("./.cache"),
        )
        assert s.CHUNK_SIZE == 1500
        assert s.RERANK_TOP_K == 5
        assert s.langfuse_enabled is False

    def test_langfuse_enabled_when_keys_present(self) -> None:
        s = Settings(
            OPENAI_API_KEY="sk-test",
            QWEN_API_KEY=None,
            QDRANT_URL=None,
            QDRANT_API_KEY=None,
            QDRANT_PATH="./qdrant_storage",
            QDRANT_COLLECTION="adaptive_rag",
            DENSE_MODEL="text-embedding-3-small",
            DENSE_SIZE=1536,
            SPARSE_MODEL="Qdrant/bm25",
            CHUNK_SIZE=1500,
            CHUNK_OVERLAP=200,
            RETRIEVAL_PREFETCH_K=25,
            RERANK_TOP_K=5,
            RERANKER_MODEL="ms-marco-MiniLM-L-12-v2",
            LLM_MODEL="gpt-4.1-mini",
            LLM_TEMPERATURE=0.2,
            LLM_MAX_TOKENS=1024,
            ROUTER_MODEL="gpt-4.1-nano",
            ROUTER_TEMPERATURE=0.0,
            SQL_MODEL="gpt-4.1-mini",
            SQL_DATABASE_URL=None,
            SQL_QUERY_TIMEOUT_SEC=5,
            SQL_ROW_LIMIT=200,
            LANGFUSE_PUBLIC_KEY="pk_test",
            LANGFUSE_SECRET_KEY="sk_test",
            LANGFUSE_HOST="https://cloud.langfuse.com",
            CACHE_DIR=Path("./.cache"),
        )
        assert s.langfuse_enabled is True

    def test_frozen_prevents_mutation(self) -> None:
        s = Settings(
            OPENAI_API_KEY=None,
            QWEN_API_KEY=None,
            QDRANT_URL=None,
            QDRANT_API_KEY=None,
            QDRANT_PATH="./qdrant_storage",
            QDRANT_COLLECTION="adaptive_rag",
            DENSE_MODEL="text-embedding-3-small",
            DENSE_SIZE=1536,
            SPARSE_MODEL="Qdrant/bm25",
            CHUNK_SIZE=1500,
            CHUNK_OVERLAP=200,
            RETRIEVAL_PREFETCH_K=25,
            RERANK_TOP_K=5,
            RERANKER_MODEL="ms-marco-MiniLM-L-12-v2",
            LLM_MODEL="gpt-4.1-mini",
            LLM_TEMPERATURE=0.2,
            LLM_MAX_TOKENS=1024,
            ROUTER_MODEL="gpt-4.1-nano",
            ROUTER_TEMPERATURE=0.0,
            SQL_MODEL="gpt-4.1-mini",
            SQL_DATABASE_URL=None,
            SQL_QUERY_TIMEOUT_SEC=5,
            SQL_ROW_LIMIT=200,
            LANGFUSE_PUBLIC_KEY=None,
            LANGFUSE_SECRET_KEY=None,
            LANGFUSE_HOST="https://cloud.langfuse.com",
            CACHE_DIR=Path("./.cache"),
        )
        with pytest.raises(AttributeError):
            s.CHUNK_SIZE = 999  # type: ignore[misc]
