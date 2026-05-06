"""Vector indexing layer (embeddings + Qdrant + ingestion pipeline)."""

from .embeddings import build_dense_embeddings, build_sparse_embeddings
from .pipeline import IngestionPipeline, IngestionResult
from .qdrant_store import (
    DENSE_VECTOR_NAME,
    SPARSE_VECTOR_NAME,
    QdrantStore,
    QdrantStoreError,
)

__all__ = [
    "DENSE_VECTOR_NAME",
    "IngestionPipeline",
    "IngestionResult",
    "QdrantStore",
    "QdrantStoreError",
    "SPARSE_VECTOR_NAME",
    "build_dense_embeddings",
    "build_sparse_embeddings",
]
