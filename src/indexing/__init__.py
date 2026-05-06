"""Vector indexing layer (embeddings + Qdrant + ingestion pipeline)."""

from .embeddings import (
    DEFAULT_DENSE_MODEL,
    DEFAULT_DENSE_SIZE,
    DEFAULT_SPARSE_MODEL,
    build_dense_embeddings,
    build_sparse_embeddings,
)
from .pipeline import IngestionPipeline, IngestionResult
from .qdrant_store import QdrantStore, QdrantStoreError

__all__ = [
    "DEFAULT_DENSE_MODEL",
    "DEFAULT_DENSE_SIZE",
    "DEFAULT_SPARSE_MODEL",
    "build_dense_embeddings",
    "build_sparse_embeddings",
    "IngestionPipeline",
    "IngestionResult",
    "QdrantStore",
    "QdrantStoreError",
]
