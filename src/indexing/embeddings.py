"""Embedding factories.

We use:

- **Dense**: OpenAI ``text-embedding-3-small`` (1536 dim) — cheap, decent quality.
  Wrapped in a disk cache so re-embedding the same chunk is free.
- **Sparse**: FastEmbed BM25 (``Qdrant/bm25``) — local, no API cost,
  pairs with Qdrant's IDF modifier for proper BM25 scoring.

Set ``HF_HUB_DISABLE_SYMLINKS=1`` so FastEmbed model downloads don't
trigger Windows symlink-permission errors.

All defaults flow from :mod:`src.config.settings` — override them via
``.env`` (e.g. ``DENSE_MODEL=text-embedding-3-large``).
"""

from __future__ import annotations

import logging
import os

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS", "1")

from langchain_core.embeddings import Embeddings
from langchain_openai import OpenAIEmbeddings
from langchain_qdrant import FastEmbedSparse

from src.cache import cached_embeddings
from src.config import settings

logger = logging.getLogger(__name__)


def build_dense_embeddings(
    model: str | None = None,
    *,
    use_cache: bool = True,
) -> Embeddings:
    """Return a configured OpenAI dense embedder, optionally cached on disk."""
    model = model or settings.DENSE_MODEL
    if not settings.OPENAI_API_KEY:
        raise RuntimeError(
            "OPENAI_API_KEY is not set. Add it to .env to enable dense embeddings."
        )

    base = OpenAIEmbeddings(model=model)
    if not use_cache:
        return base

    return cached_embeddings(
        base,
        namespace=model,
        cache_dir=settings.CACHE_DIR / "embeddings",
    )


def build_sparse_embeddings(model: str | None = None) -> FastEmbedSparse:
    """Return a FastEmbed BM25 sparse embedder.

    Lazy-downloads the tokenizer files (~few MB) on first use.

    NOTE: ``disable_stemmer=True`` is a temporary workaround for a
    Python 3.14 segfault in ``py-rust-stemmers`` 0.1.5
    (see https://github.com/qdrant/py-rust-stemmers/pull/9). Drop the kwarg
    once a fixed release is published — quality recovers slightly on
    stemming-sensitive queries (e.g. "running" vs "runs").
    """
    model = model or settings.SPARSE_MODEL
    logger.info(f"Initializing sparse embeddings: {model} (stemmer disabled)")
    return FastEmbedSparse(model_name=model, disable_stemmer=True)
