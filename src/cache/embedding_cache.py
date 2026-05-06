"""Persistent disk cache for dense embeddings.

LangChain v1 moved ``CacheBackedEmbeddings`` into the optional
``langchain-classic`` package. To avoid pulling in a legacy package for a
30-line feature, we ship our own ``Embeddings`` adapter that disk-caches by
SHA256(model_name + text). Cached values are stored as raw float32 bytes —
~6 KB per 1536-dim embedding.
"""

from __future__ import annotations

import array
import hashlib
import logging
from pathlib import Path

from langchain_core.embeddings import Embeddings

logger = logging.getLogger(__name__)


class _CachedEmbeddings(Embeddings):
    """Wrap any ``Embeddings`` with a per-text disk cache."""

    def __init__(
        self,
        underlying: Embeddings,
        *,
        namespace: str,
        cache_dir: Path,
    ) -> None:
        self._underlying = underlying
        self._namespace = namespace
        self._cache_dir = cache_dir
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    # ---- Embeddings interface -----------------------------------------

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        results: list[list[float] | None] = [None] * len(texts)
        misses: list[int] = []
        miss_texts: list[str] = []

        for i, text in enumerate(texts):
            cached = self._read(text)
            if cached is not None:
                results[i] = cached
            else:
                misses.append(i)
                miss_texts.append(text)

        if miss_texts:
            logger.info(
                f"Embedding cache: {len(texts) - len(misses)} hits, "
                f"{len(misses)} misses → calling model"
            )
            fresh = self._underlying.embed_documents(miss_texts)
            for idx, vec in zip(misses, fresh, strict=True):
                results[idx] = vec
                self._write(texts[idx], vec)
        else:
            logger.info(f"Embedding cache: all {len(texts)} hits")

        return [r for r in results if r is not None]

    def embed_query(self, text: str) -> list[float]:
        cached = self._read(text)
        if cached is not None:
            return cached
        vec = self._underlying.embed_query(text)
        self._write(text, vec)
        return vec

    # ---- internals ----------------------------------------------------

    def _key(self, text: str) -> str:
        h = hashlib.sha256()
        h.update(self._namespace.encode("utf-8"))
        h.update(b"\x00")
        h.update(text.encode("utf-8"))
        return h.hexdigest()

    def _path(self, text: str) -> Path:
        return self._cache_dir / f"{self._key(text)}.bin"

    def _read(self, text: str) -> list[float] | None:
        path = self._path(text)
        if not path.exists():
            return None
        try:
            arr = array.array("f")
            arr.frombytes(path.read_bytes())
            return arr.tolist()
        except OSError as exc:
            logger.warning(f"Embedding cache read failed for {path.name}: {exc}")
            return None

    def _write(self, text: str, vector: list[float]) -> None:
        path = self._path(text)
        try:
            arr = array.array("f", vector)
            path.write_bytes(arr.tobytes())
        except OSError as exc:
            logger.warning(f"Embedding cache write failed for {path.name}: {exc}")


def cached_embeddings(
    underlying: Embeddings,
    *,
    namespace: str,
    cache_dir: str | Path = ".cache/embeddings",
) -> Embeddings:
    """Return ``underlying`` wrapped in a SHA256-keyed disk cache.

    ``namespace`` distinguishes outputs from different models — typically pass
    the model name. Same text + different namespace → different cache entry.
    """
    return _CachedEmbeddings(
        underlying,
        namespace=namespace,
        cache_dir=Path(cache_dir),
    )
