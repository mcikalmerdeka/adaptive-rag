"""Tests for src.config.settings — env var parsing, defaults, immutability."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
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
            ZAI_API_KEY=None,
            ZAI_BASE_URL="https://api.z.ai/api/paas/v4/",
            GLM_MODEL="glm-5.3-flash",
            GLM_REASONING_EFFORT="low",
            GLM_MAX_TOKENS=8192,
            GLM_VIDEO_MAX_UPLOAD_MB=20,
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
            LLM_MODEL="gpt-6-luna",
            LLM_TEMPERATURE=0.2,
            LLM_MAX_TOKENS=4096,
            LLM_REASONING_EFFORT="high",
            ROUTER_MODEL="gpt-6-luna",
            ROUTER_TEMPERATURE=0.0,
            ROUTER_REASONING_EFFORT="none",
            SQL_MODEL="gpt-6-luna",
            SQL_REASONING_EFFORT="high",
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
        assert s.GLM_MODEL == "glm-5.3-flash"
        assert s.ZAI_BASE_URL == "https://api.z.ai/api/paas/v4/"
        assert s.GLM_REASONING_EFFORT == "low"
        assert s.GLM_MAX_TOKENS == 8192
        assert s.GLM_VIDEO_MAX_UPLOAD_MB == 20

    def test_langfuse_enabled_when_keys_present(self) -> None:
        s = Settings(
            OPENAI_API_KEY="sk-test",
            ZAI_API_KEY=None,
            ZAI_BASE_URL="https://api.z.ai/api/paas/v4/",
            GLM_MODEL="glm-5.3-flash",
            GLM_REASONING_EFFORT="low",
            GLM_MAX_TOKENS=8192,
            GLM_VIDEO_MAX_UPLOAD_MB=20,
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
            LLM_MODEL="gpt-6-luna",
            LLM_TEMPERATURE=0.2,
            LLM_MAX_TOKENS=4096,
            LLM_REASONING_EFFORT="high",
            ROUTER_MODEL="gpt-6-luna",
            ROUTER_TEMPERATURE=0.0,
            ROUTER_REASONING_EFFORT="none",
            SQL_MODEL="gpt-6-luna",
            SQL_REASONING_EFFORT="high",
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
            ZAI_API_KEY=None,
            ZAI_BASE_URL="https://api.z.ai/api/paas/v4/",
            GLM_MODEL="glm-5.3-flash",
            GLM_REASONING_EFFORT="low",
            GLM_MAX_TOKENS=8192,
            GLM_VIDEO_MAX_UPLOAD_MB=20,
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
            LLM_MODEL="gpt-6-luna",
            LLM_TEMPERATURE=0.2,
            LLM_MAX_TOKENS=4096,
            LLM_REASONING_EFFORT="high",
            ROUTER_MODEL="gpt-6-luna",
            ROUTER_TEMPERATURE=0.0,
            ROUTER_REASONING_EFFORT="none",
            SQL_MODEL="gpt-6-luna",
            SQL_REASONING_EFFORT="high",
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


# ---------------------------------------------------------------------------
# Reasoning-mode properties (gpt-5.6 family)
# ---------------------------------------------------------------------------


def _settings_with(**overrides: Any) -> Settings:
    """Build a Settings instance from the documented defaults."""
    values: dict[str, Any] = dict(
        OPENAI_API_KEY=None,
        ZAI_API_KEY=None,
        ZAI_BASE_URL="https://api.z.ai/api/paas/v4/",
        GLM_MODEL="glm-5.3-flash",
        GLM_REASONING_EFFORT="low",
        GLM_MAX_TOKENS=8192,
        GLM_VIDEO_MAX_UPLOAD_MB=20,
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
        LLM_MODEL="gpt-6-luna",
        LLM_TEMPERATURE=0.2,
        LLM_MAX_TOKENS=4096,
        LLM_REASONING_EFFORT="high",
        ROUTER_MODEL="gpt-6-luna",
        ROUTER_TEMPERATURE=0.0,
        ROUTER_REASONING_EFFORT="none",
        SQL_MODEL="gpt-6-luna",
        SQL_REASONING_EFFORT="high",
        SQL_DATABASE_URL=None,
        SQL_QUERY_TIMEOUT_SEC=5,
        SQL_ROW_LIMIT=200,
        LANGFUSE_PUBLIC_KEY=None,
        LANGFUSE_SECRET_KEY=None,
        LANGFUSE_HOST="https://cloud.langfuse.com",
        CACHE_DIR=Path("./.cache"),
    )
    values.update(overrides)
    return Settings(**values)


class TestReasoningEffort:
    """llm_reasoning / sql_reasoning / router_reasoning property behavior."""

    def test_configured_efforts_are_the_defaults(self) -> None:
        s = _settings_with()
        assert s.llm_reasoning == {"effort": "high"}
        assert s.sql_reasoning == {"effort": "high"}
        assert s.router_reasoning == {"effort": "none"}

    def test_off_omits_the_reasoning_parameter(self) -> None:
        s = _settings_with(
            LLM_REASONING_EFFORT="off",
            SQL_REASONING_EFFORT="off",
            ROUTER_REASONING_EFFORT="off",
        )
        assert s.llm_reasoning is None
        assert s.sql_reasoning is None
        assert s.router_reasoning is None

    def test_effort_passes_through(self) -> None:
        s = _settings_with(SQL_REASONING_EFFORT="low", ROUTER_REASONING_EFFORT="low")
        assert s.llm_reasoning == {"effort": "high"}
        assert s.sql_reasoning == {"effort": "low"}
        assert s.router_reasoning == {"effort": "low"}


class TestTemperatureOmission:
    """Reasoning models at effort != none reject the temperature param.

    Observed live on gpt-6-luna: 400 "Unsupported parameter: 'temperature'
    is not supported with this model" at effort high; accepted at effort
    none. Temperature is only meaningful for non-reasoning fallback models.
    """

    def test_temperature_omitted_while_reasoning_is_active(self) -> None:
        s = _settings_with()
        assert s.llm_temperature is None
        assert s.sql_temperature is None

    def test_temperature_kept_at_effort_none(self) -> None:
        s = _settings_with(
            LLM_REASONING_EFFORT="none",
            SQL_REASONING_EFFORT="none",
        )
        assert s.llm_temperature == 0.2
        assert s.sql_temperature == 0.0
        # Router default is already effort none — temperature applies.
        assert s.router_temperature == 0.0

    def test_router_temperature_omitted_when_effort_raised(self) -> None:
        s = _settings_with(ROUTER_REASONING_EFFORT="high")
        assert s.router_temperature is None

    def test_temperature_kept_when_reasoning_off(self) -> None:
        s = _settings_with(
            LLM_REASONING_EFFORT="off",
            SQL_REASONING_EFFORT="off",
            ROUTER_REASONING_EFFORT="off",
        )
        assert s.llm_temperature == 0.2
        assert s.sql_temperature == 0.0
        assert s.router_temperature == 0.0
