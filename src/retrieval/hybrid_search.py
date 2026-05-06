"""Hybrid (dense + sparse) retrieval against the Qdrant store.

The Qdrant collection is created in HYBRID retrieval mode with named
``"dense"`` and ``"sparse"`` vector fields and the BM25 IDF modifier on the
sparse side. ``QdrantVectorStore.similarity_search_with_score`` issues a
single request that does:

1. Dense ANN prefetch (k = ``RETRIEVAL_PREFETCH_K``).
2. Sparse BM25 prefetch (k = ``RETRIEVAL_PREFETCH_K``).
3. Server-side RRF fusion of both candidate lists.

We expose two surfaces:

- :class:`HybridRetriever` — raw fused candidates from Qdrant.
- :class:`RetrievalPipeline` — fused candidates + cross-encoder reranking +
  trim to ``RERANK_TOP_K``. This is what the chat layer should use.

Citations are produced from the per-chunk metadata that the indexing layer
already attaches (``filename``, ``header_path``, ``chunk_index``, etc.).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from langchain_core.documents import Document

from src.config import settings
from src.indexing import QdrantStore

from .reranker import Reranker, RerankerError

logger = logging.getLogger(__name__)


@dataclass
class RetrievedChunk:
    """A single retrieved chunk plus the scores attached to it.

    ``hybrid_score`` is the RRF-fused score from Qdrant. ``rerank_score`` is
    populated only after the reranker has run; ``None`` means it was
    skipped (reranker disabled or unavailable).
    """

    document: Document
    hybrid_score: float
    rerank_score: float | None = None
    rank: int = 0  # final 1-based rank in the returned list

    # Convenience accessors -------------------------------------------------

    @property
    def text(self) -> str:
        return self.document.page_content

    @property
    def metadata(self) -> dict[str, Any]:
        return self.document.metadata or {}

    def citation_label(self) -> str:
        """A short human-readable label, e.g. ``"policy.pdf > Refunds (chunk 3)"``."""
        meta = self.metadata
        filename = meta.get("filename") or meta.get("source") or "unknown"
        header = meta.get("header_path") or ""
        chunk_idx = meta.get("chunk_index")

        parts = [filename]
        if header:
            parts.append(header)
        label = " > ".join(parts)
        if chunk_idx is not None:
            label = f"{label} (chunk {chunk_idx})"
        return label


@dataclass
class RetrievalReport:
    """Diagnostic info you can show in the UI or log for debugging."""

    query: str
    fused_count: int
    final_count: int
    reranker_used: bool
    fused_ms: float
    rerank_ms: float
    chunks: list[RetrievedChunk] = field(default_factory=list)


class HybridRetriever:
    """Thin wrapper over the Qdrant hybrid store."""

    def __init__(self, store: QdrantStore | None = None) -> None:
        self._store = store or QdrantStore()

    @property
    def store(self) -> QdrantStore:
        return self._store

    def search(
        self,
        query: str,
        *,
        k: int | None = None,
    ) -> list[RetrievedChunk]:
        k = k or settings.RETRIEVAL_PREFETCH_K
        try:
            results = self._store.vector_store.similarity_search_with_score(
                query=query,
                k=k,
            )
        except Exception as exc:
            logger.exception("Hybrid search failed")
            raise RetrievalError(f"Hybrid search failed: {exc}") from exc

        return [
            RetrievedChunk(document=doc, hybrid_score=float(score))
            for doc, score in results
        ]


class RetrievalError(Exception):
    """Raised on retrieval failures (Qdrant unreachable, etc.)."""


class RetrievalPipeline:
    """End-to-end retrieval: hybrid prefetch → rerank → trim.

    Intended call site::

        pipeline = RetrievalPipeline()
        report = pipeline.retrieve("how do refunds work?")
        for chunk in report.chunks:
            print(chunk.citation_label(), chunk.rerank_score)
    """

    def __init__(
        self,
        retriever: HybridRetriever | None = None,
        reranker: Reranker | None | bool = None,
    ) -> None:
        """Create the pipeline.

        ``reranker``:
        - ``None`` (default): build a Reranker lazily on first use.
        - ``False``: disable reranking entirely (return hybrid order, trimmed
          to ``RERANK_TOP_K``).
        - A ``Reranker`` instance: use it as-is.
        """
        self._retriever = retriever or HybridRetriever()
        if reranker is False:
            self._reranker: Reranker | None = None
            self._reranker_disabled = True
        else:
            self._reranker = reranker if isinstance(reranker, Reranker) else None
            self._reranker_disabled = False

    @property
    def retriever(self) -> HybridRetriever:
        return self._retriever

    @property
    def reranker_active(self) -> bool:
        """True if a reranker will run on the next call."""
        return not self._reranker_disabled

    def _get_reranker(self) -> Reranker | None:
        if self._reranker_disabled:
            return None
        if self._reranker is None:
            try:
                self._reranker = Reranker()
            except RerankerError as exc:
                logger.warning(f"Reranker unavailable, skipping: {exc}")
                self._reranker_disabled = True
                return None
        return self._reranker

    def retrieve(
        self,
        query: str,
        *,
        prefetch_k: int | None = None,
        top_k: int | None = None,
    ) -> RetrievalReport:
        prefetch_k = prefetch_k or settings.RETRIEVAL_PREFETCH_K
        top_k = top_k or settings.RERANK_TOP_K

        if not query.strip():
            return RetrievalReport(
                query=query,
                fused_count=0,
                final_count=0,
                reranker_used=False,
                fused_ms=0.0,
                rerank_ms=0.0,
            )

        # 1. hybrid prefetch
        t0 = time.perf_counter()
        candidates = self._retriever.search(query, k=prefetch_k)
        fused_ms = (time.perf_counter() - t0) * 1000

        if not candidates:
            return RetrievalReport(
                query=query,
                fused_count=0,
                final_count=0,
                reranker_used=False,
                fused_ms=fused_ms,
                rerank_ms=0.0,
            )

        # 2. rerank (or skip)
        reranker = self._get_reranker()
        rerank_ms = 0.0
        if reranker is not None:
            t1 = time.perf_counter()
            try:
                candidates = reranker.rerank(query, candidates)
            except RerankerError as exc:
                logger.warning(f"Rerank failed, falling back to hybrid order: {exc}")
                self._reranker_disabled = True
            rerank_ms = (time.perf_counter() - t1) * 1000

        # 3. trim
        final = candidates[:top_k]
        for i, chunk in enumerate(final, start=1):
            chunk.rank = i

        logger.info(
            f"retrieve('{query[:40]}…'): fused={len(candidates)} "
            f"({fused_ms:.0f}ms) → top {len(final)} "
            f"(rerank {rerank_ms:.0f}ms, used={reranker is not None})"
        )

        return RetrievalReport(
            query=query,
            fused_count=len(candidates),
            final_count=len(final),
            reranker_used=reranker is not None,
            fused_ms=fused_ms,
            rerank_ms=rerank_ms,
            chunks=final,
        )
