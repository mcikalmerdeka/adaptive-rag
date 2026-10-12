"""Single source of truth for all user-tunable settings.

Loads ``.env`` once on import. Each setting reads ``os.getenv`` with a
sensible default, so omitting the variable just gets you the default.
We deliberately avoid Pydantic Settings here — a 70-line module is easier
to grep than a magic schema, and we don't need cross-field validation yet.

Internal constants that nobody should change at runtime (vector field
names, namespace UUIDs, etc.) deliberately live next to their consumer.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return int(raw) if raw not in (None, "") else default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    return float(raw) if raw not in (None, "") else default


def _env_str(name: str, default: str) -> str:
    raw = os.getenv(name)
    return raw if raw not in (None, "") else default


def _env_optional(name: str) -> str | None:
    raw = os.getenv(name)
    return raw if raw not in (None, "") else None


@dataclass(frozen=True)
class Settings:
    """Immutable runtime settings.

    Frozen dataclass so a typo like ``settings.RERANK_TOP_K = 10`` blows up
    immediately instead of silently being a no-op for other modules that
    already imported the value.
    """

    # ---- API keys ----
    OPENAI_API_KEY: str | None
    # Z.ai GLM-5.3-Flash (vision OCR: images, scanned PDFs, videos).
    ZAI_API_KEY: str | None
    ZAI_BASE_URL: str
    GLM_MODEL: str
    GLM_REASONING_EFFORT: str
    GLM_MAX_TOKENS: int
    GLM_VIDEO_MAX_UPLOAD_MB: int

    # ---- Qdrant ----
    QDRANT_URL: str | None
    QDRANT_API_KEY: str | None
    QDRANT_PATH: str
    QDRANT_COLLECTION: str

    # ---- Embeddings ----
    DENSE_MODEL: str
    DENSE_SIZE: int
    SPARSE_MODEL: str

    # ---- Chunking ----
    CHUNK_SIZE: int
    CHUNK_OVERLAP: int

    # ---- Retrieval & reranking ----
    RETRIEVAL_PREFETCH_K: int  # candidates fetched from Qdrant (per query)
    RERANK_TOP_K: int          # final chunks returned after reranker

    # ---- Reranker ----
    RERANKER_MODEL: str

    # ---- LLM (synthesis) ----
    LLM_MODEL: str
    LLM_TEMPERATURE: float
    LLM_MAX_TOKENS: int
    # Reasoning effort for the gpt-6/gpt-5.6 families: "none" | "minimal" |
    # "low" | "medium" | "high" | "xhigh" | "max" (values are model-dependent;
    # "off" = omit the reasoning parameter, for models outside those families).
    LLM_REASONING_EFFORT: str | None

    # ---- Adaptive router (Phase 5) ----
    ROUTER_MODEL: str
    ROUTER_TEMPERATURE: float
    # Router classification runs at effort "none": gpt-6 models only allow
    # function calling (structured output) on Chat Completions at effort none,
    # and classification doesn't benefit from reasoning anyway.
    ROUTER_REASONING_EFFORT: str | None
    SQL_MODEL: str
    # Same semantics as LLM_REASONING_EFFORT, for the NL->SQL translator.
    SQL_REASONING_EFFORT: str | None

    # ---- SQL tool (Phase 5) ----
    SQL_DATABASE_URL: str | None
    SQL_QUERY_TIMEOUT_SEC: int
    SQL_ROW_LIMIT: int

    # ---- Langfuse (Phase 6) ----
    LANGFUSE_PUBLIC_KEY: str | None
    LANGFUSE_SECRET_KEY: str | None
    LANGFUSE_HOST: str

    # ---- Cache directories ----
    CACHE_DIR: Path

    @property
    def langfuse_enabled(self) -> bool:
        """True when both Langfuse keys are present."""
        return bool(self.LANGFUSE_PUBLIC_KEY and self.LANGFUSE_SECRET_KEY)

    @property
    def llm_reasoning(self) -> dict[str, str] | None:
        """Responses API ``reasoning`` payload for the synthesis LLM.

        ``None`` omits the parameter entirely — set ``LLM_REASONING_EFFORT=off``
        when swapping ``LLM_MODEL`` to a model outside the gpt-6/gpt-5.6
        families, which rejects the parameter with a 400.
        """
        if self.LLM_REASONING_EFFORT in (None, "", "off"):
            return None
        return {"effort": self.LLM_REASONING_EFFORT}

    @property
    def router_reasoning(self) -> dict[str, str] | None:
        """Same as :attr:`llm_reasoning`, for the strategy classifier."""
        if self.ROUTER_REASONING_EFFORT in (None, "", "off"):
            return None
        return {"effort": self.ROUTER_REASONING_EFFORT}

    @property
    def sql_reasoning(self) -> dict[str, str] | None:
        """Same as :attr:`llm_reasoning`, for the NL→SQL translator."""
        if self.SQL_REASONING_EFFORT in (None, "", "off"):
            return None
        return {"effort": self.SQL_REASONING_EFFORT}

    # ---- temperature gating ------------------------------------------------

    @property
    def llm_temperature(self) -> float | None:
        """Temperature for the synthesis call; ``None`` omits the parameter.

        Reasoning models reject ``temperature`` at any effort other than
        ``none`` (observed live on gpt-6-luna: 400 "Unsupported parameter").
        Omit it while reasoning is active; restore it at effort ``none`` and
        for ``off`` (non-reasoning fallback models, e.g. gpt-4.1-mini).
        """
        if self.LLM_REASONING_EFFORT not in (None, "", "off", "none"):
            return None
        return self.LLM_TEMPERATURE

    @property
    def router_temperature(self) -> float | None:
        """Same rule as :attr:`llm_temperature`, for the router call."""
        if self.ROUTER_REASONING_EFFORT not in (None, "", "off", "none"):
            return None
        return self.ROUTER_TEMPERATURE

    @property
    def sql_temperature(self) -> float | None:
        """Same rule as :attr:`llm_temperature`, for the NL→SQL call.

        ``0.0`` for non-reasoning fallback models; omitted while reasoning
        is active at an effort other than ``none``.
        """
        if self.SQL_REASONING_EFFORT not in (None, "", "off", "none"):
            return None
        return 0.0


def _load() -> Settings:
    return Settings(
        OPENAI_API_KEY=_env_optional("OPENAI_API_KEY"),
        ZAI_API_KEY=_env_optional("ZAI_API_KEY"),
        # Z.ai's official OpenAI-compatible PAAS v4 endpoint
        # (https://docs.z.ai/api-reference/llm/chat-completion).
        ZAI_BASE_URL=_env_str("ZAI_BASE_URL", "https://api.z.ai/api/paas/v4/"),
        GLM_MODEL=_env_str("GLM_MODEL", "glm-5.3-flash"),
        # Flash supports low/high/max only (docs.z.ai/guides/vlm/glm-5.3-flash).
        GLM_REASONING_EFFORT=_env_str("GLM_REASONING_EFFORT", "low"),
        GLM_MAX_TOKENS=_env_int("GLM_MAX_TOKENS", 8192),
        # Base64 inflates videos ×1.33; Z.ai's documented URL mode allows
        # 200 MB, but huge base64 bodies get rejected — keep uploads sane.
        GLM_VIDEO_MAX_UPLOAD_MB=_env_int("GLM_VIDEO_MAX_UPLOAD_MB", 20),
        QDRANT_URL=_env_optional("QDRANT_URL"),
        QDRANT_API_KEY=_env_optional("QDRANT_API_KEY"),
        QDRANT_PATH=_env_str("QDRANT_PATH", "./qdrant_storage"),
        QDRANT_COLLECTION=_env_str("QDRANT_COLLECTION", "adaptive_rag"),
        DENSE_MODEL=_env_str("DENSE_MODEL", "text-embedding-3-small"),
        DENSE_SIZE=_env_int("DENSE_SIZE", 1536),
        SPARSE_MODEL=_env_str("SPARSE_MODEL", "Qdrant/bm25"),
        CHUNK_SIZE=_env_int("CHUNK_SIZE", 1500),
        CHUNK_OVERLAP=_env_int("CHUNK_OVERLAP", 200),
        RETRIEVAL_PREFETCH_K=_env_int("RETRIEVAL_PREFETCH_K", 25),
        RERANK_TOP_K=_env_int("RERANK_TOP_K", 5),
        RERANKER_MODEL=_env_str("RERANKER_MODEL", "ms-marco-MiniLM-L-12-v2"),
        LLM_MODEL=_env_str("LLM_MODEL", "gpt-6-luna"),
        # NOTE: reasoning models reject the temperature parameter at any
        # effort other than none (gpt-6-luna 400s); llm_temperature omits
        # it automatically. This knob applies to effort none / fallback models.
        LLM_TEMPERATURE=_env_float("LLM_TEMPERATURE", 0.2),
        # High-effort reasoning tokens count toward the output budget —
        # small budgets truncate grounded answers, so leave headroom.
        LLM_MAX_TOKENS=_env_int("LLM_MAX_TOKENS", 4096),
        LLM_REASONING_EFFORT=_env_str("LLM_REASONING_EFFORT", "high"),
        ROUTER_MODEL=_env_str("ROUTER_MODEL", "gpt-6-luna"),
        ROUTER_TEMPERATURE=_env_float("ROUTER_TEMPERATURE", 0.0),
        ROUTER_REASONING_EFFORT=_env_str("ROUTER_REASONING_EFFORT", "none"),
        SQL_MODEL=_env_str("SQL_MODEL", "gpt-6-luna"),
        SQL_REASONING_EFFORT=_env_str("SQL_REASONING_EFFORT", "high"),
        SQL_DATABASE_URL=_env_optional("SQL_DATABASE_URL"),
        SQL_QUERY_TIMEOUT_SEC=_env_int("SQL_QUERY_TIMEOUT_SEC", 5),
        SQL_ROW_LIMIT=_env_int("SQL_ROW_LIMIT", 200),
        LANGFUSE_PUBLIC_KEY=_env_optional("LANGFUSE_PUBLIC_KEY"),
        LANGFUSE_SECRET_KEY=_env_optional("LANGFUSE_SECRET_KEY"),
        LANGFUSE_HOST=_env_str("LANGFUSE_HOST", "https://cloud.langfuse.com"),
        CACHE_DIR=Path(_env_str("CACHE_DIR", "./.cache")),
    )


settings: Settings = _load()
