"""Retrieval layer.

Two pieces:

- :class:`HybridRetriever` — hybrid (dense + sparse) search against Qdrant
  with server-side RRF fusion.
- :class:`Reranker` — cross-encoder reranker (FlashRank, ONNX) that reorders
  the candidates and trims to ``settings.RERANK_TOP_K``.

Both are composed by :class:`RetrievalPipeline`, which is what the chat /
synthesis layer talks to.
"""

from .hybrid_search import HybridRetriever, RetrievalPipeline, RetrievedChunk
from .reranker import Reranker, RerankerError

__all__ = [
    "HybridRetriever",
    "RetrievalPipeline",
    "RetrievedChunk",
    "Reranker",
    "RerankerError",
]
