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
    QWEN_API_KEY: str | None

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

    # ---- Cache directories ----
    CACHE_DIR: Path


def _load() -> Settings:
    return Settings(
        OPENAI_API_KEY=_env_optional("OPENAI_API_KEY"),
        QWEN_API_KEY=_env_optional("QWEN_API_KEY"),
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
        LLM_MODEL=_env_str("LLM_MODEL", "gpt-4.1-mini"),
        LLM_TEMPERATURE=_env_float("LLM_TEMPERATURE", 0.2),
        LLM_MAX_TOKENS=_env_int("LLM_MAX_TOKENS", 1024),
        CACHE_DIR=Path(_env_str("CACHE_DIR", "./.cache")),
    )


settings: Settings = _load()
