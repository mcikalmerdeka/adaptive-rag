"""Cross-encoder reranker built on FlashRank.

Why FlashRank:

- Pure ONNX, no PyTorch / Transformers — keeps the install slim and avoids
  the same Python-3.14 native-extension headaches we hit with
  ``py-rust-stemmers``.
- ``ms-marco-MiniLM-L-12-v2`` (~34 MB) gives near-state-of-the-art reranking
  on English with ~10–30 ms per pair on CPU.
- Lazy model download: the ONNX file is fetched on first use, then cached.

Defaults flow from :mod:`src.config.settings.RERANKER_MODEL`. Override via
``RERANKER_MODEL=ms-marco-TinyBERT-L-2-v2`` (4 MB, fastest) or
``rank-T5-flan`` (110 MB, best quality).

Failure modes:

- If FlashRank can't be imported (broken install) or the model can't be
  downloaded, we raise :class:`RerankerError`. The retrieval pipeline
  catches it and silently falls back to hybrid-fusion order.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from src.config import settings

if TYPE_CHECKING:
    from .hybrid_search import RetrievedChunk

logger = logging.getLogger(__name__)


class RerankerError(Exception):
    """Raised when the reranker cannot be loaded or scoring fails."""


class Reranker:
    """Cross-encoder reranker (FlashRank ONNX backend)."""

    def __init__(
        self,
        model_name: str | None = None,
        cache_dir: str | Path | None = None,
        max_length: int = 512,
    ) -> None:
        try:
            from flashrank import Ranker
        except ImportError as exc:
            raise RerankerError(
                "FlashRank is not installed. Run `pip install flashrank` "
                "or remove reranking by passing reranker=False."
            ) from exc

        self.model_name = model_name or settings.RERANKER_MODEL
        cache_path = Path(cache_dir) if cache_dir else settings.CACHE_DIR / "flashrank"
        cache_path.mkdir(parents=True, exist_ok=True)

        logger.info(
            f"Initializing reranker '{self.model_name}' "
            f"(cache_dir={cache_path}, max_length={max_length})"
        )
        try:
            self._ranker = Ranker(
                model_name=self.model_name,
                cache_dir=str(cache_path),
                max_length=max_length,
            )
        except Exception as exc:
            raise RerankerError(
                f"Failed to initialize FlashRank model '{self.model_name}': {exc}"
            ) from exc

    def rerank(
        self,
        query: str,
        chunks: list[RetrievedChunk],
    ) -> list[RetrievedChunk]:
        """Score every chunk against ``query`` and return them sorted desc.

        Mutates each chunk's ``rerank_score`` in place. Empty input → empty
        output (no model call).
        """
        if not chunks:
            return []

        from flashrank import RerankRequest

        passages = [
            {"id": i, "text": chunk.text, "meta": {}}
            for i, chunk in enumerate(chunks)
        ]
        try:
            results = self._ranker.rerank(
                RerankRequest(query=query, passages=passages)
            )
        except Exception as exc:
            raise RerankerError(f"Reranking failed: {exc}") from exc

        # FlashRank returns the passages sorted by score desc, each tagged
        # with the original ``id`` we passed in. Map back to our chunks.
        reordered: list[RetrievedChunk] = []
        for r in results:
            idx = int(r["id"])
            chunk = chunks[idx]
            chunk.rerank_score = float(r["score"])
            reordered.append(chunk)

        return reordered
