"""Hybrid Qdrant collection wrapper.

Encapsulates:

- Connecting to Qdrant in either embedded mode (local file path) or
  remote/Docker/Cloud mode (HTTP URL + optional API key).
- Creating a hybrid collection (named ``"dense"`` + sparse ``"sparse"``)
  with the BM25 IDF modifier on the server side.
- Upserting LangChain ``Document`` objects with deterministic UUIDs.
- Document-level deduplication and replace operations keyed on ``doc_id``.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterable
from pathlib import Path

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_qdrant import FastEmbedSparse, QdrantVectorStore, RetrievalMode
from qdrant_client import QdrantClient, models

from src.chunking.metadata import chunk_uuid

from .embeddings import (
    DEFAULT_DENSE_SIZE,
    build_dense_embeddings,
    build_sparse_embeddings,
)

logger = logging.getLogger(__name__)

DEFAULT_COLLECTION = "adaptive_rag"
DEFAULT_LOCAL_PATH = "./qdrant_storage"
DENSE_VECTOR_NAME = "dense"
SPARSE_VECTOR_NAME = "sparse"


class QdrantStoreError(Exception):
    """Raised on Qdrant connection / setup / upsert failures."""


class QdrantStore:
    """Hybrid (dense + sparse) Qdrant store with metadata-aware dedup."""

    def __init__(
        self,
        *,
        collection_name: str | None = None,
        url: str | None = None,
        api_key: str | None = None,
        path: str | Path | None = None,
        dense_embeddings: Embeddings | None = None,
        sparse_embeddings: FastEmbedSparse | None = None,
        dense_size: int = DEFAULT_DENSE_SIZE,
    ) -> None:
        self.collection_name = (
            collection_name
            or os.getenv("QDRANT_COLLECTION")
            or DEFAULT_COLLECTION
        )
        self._dense_size = dense_size

        self._client = self._build_client(
            url=url or os.getenv("QDRANT_URL"),
            api_key=api_key or os.getenv("QDRANT_API_KEY"),
            path=path or os.getenv("QDRANT_PATH") or DEFAULT_LOCAL_PATH,
        )

        self._dense = dense_embeddings or build_dense_embeddings()
        self._sparse = sparse_embeddings or build_sparse_embeddings()

        self._ensure_collection()
        self._store = QdrantVectorStore(
            client=self._client,
            collection_name=self.collection_name,
            embedding=self._dense,
            sparse_embedding=self._sparse,
            retrieval_mode=RetrievalMode.HYBRID,
            vector_name=DENSE_VECTOR_NAME,
            sparse_vector_name=SPARSE_VECTOR_NAME,
        )

        logger.info(
            f"QdrantStore ready: collection='{self.collection_name}', "
            f"backend='{self._backend_label}', dense_dim={dense_size}"
        )

    # ---- public API ---------------------------------------------------

    @property
    def client(self) -> QdrantClient:
        return self._client

    @property
    def vector_store(self) -> QdrantVectorStore:
        return self._store

    def doc_exists(self, doc_id: str) -> bool:
        """True if at least one chunk with ``metadata.doc_id == doc_id`` exists."""
        result, _ = self._client.scroll(
            collection_name=self.collection_name,
            scroll_filter=self._doc_id_filter(doc_id),
            limit=1,
            with_payload=False,
            with_vectors=False,
        )
        return len(result) > 0

    def count_chunks_for_doc(self, doc_id: str) -> int:
        return self._client.count(
            collection_name=self.collection_name,
            count_filter=self._doc_id_filter(doc_id),
            exact=True,
        ).count

    def total_chunks(self) -> int:
        return self._client.count(
            collection_name=self.collection_name, exact=True
        ).count

    def list_documents(self) -> list[dict]:
        """Return a deduplicated list of indexed documents (one row per doc_id)."""
        seen: dict[str, dict] = {}
        next_offset = None
        while True:
            points, next_offset = self._client.scroll(
                collection_name=self.collection_name,
                limit=256,
                offset=next_offset,
                with_payload=True,
                with_vectors=False,
            )
            for p in points:
                meta = (p.payload or {}).get("metadata") or {}
                did = meta.get("doc_id")
                if not did or did in seen:
                    continue
                seen[did] = {
                    "doc_id": did,
                    "filename": meta.get("filename"),
                    "parser": meta.get("parser"),
                    "ingested_at": meta.get("ingested_at"),
                    "total_chunks": meta.get("total_chunks"),
                    "extension": meta.get("extension"),
                }
            if next_offset is None:
                break
        return sorted(seen.values(), key=lambda d: d.get("ingested_at") or "")

    def delete_doc(self, doc_id: str) -> int:
        before = self.count_chunks_for_doc(doc_id)
        if before == 0:
            return 0
        self._client.delete(
            collection_name=self.collection_name,
            points_selector=self._doc_id_filter(doc_id),
            wait=True,
        )
        logger.info(f"Deleted {before} chunks for doc_id={doc_id}")
        return before

    def upsert_chunks(
        self,
        chunks: Iterable[Document],
        *,
        doc_id: str,
        replace_existing: bool = True,
    ) -> int:
        """Upsert all chunks for a single document.

        With ``replace_existing=True`` (the default) any prior points for
        the same ``doc_id`` are deleted first. This makes re-ingestion
        idempotent — useful when you change parser/chunk settings.

        Returns the number of chunks inserted.
        """
        chunks = list(chunks)
        if not chunks:
            return 0

        if replace_existing:
            self.delete_doc(doc_id)

        ids = [chunk_uuid(doc_id, i) for i in range(len(chunks))]
        try:
            self._store.add_documents(documents=chunks, ids=ids)
        except Exception as exc:
            raise QdrantStoreError(
                f"Failed to upsert {len(chunks)} chunks for doc_id={doc_id}: {exc}"
            ) from exc

        logger.info(
            f"Upserted {len(chunks)} chunks for doc_id={doc_id} "
            f"(collection='{self.collection_name}')"
        )
        return len(chunks)

    # ---- internals ----------------------------------------------------

    def _build_client(
        self,
        *,
        url: str | None,
        api_key: str | None,
        path: str | Path,
    ) -> QdrantClient:
        try:
            if url:
                self._backend_label = f"remote:{url}"
                return QdrantClient(url=url, api_key=api_key)
            self._backend_label = f"embedded:{path}"
            Path(path).mkdir(parents=True, exist_ok=True)
            return QdrantClient(path=str(path))
        except Exception as exc:
            raise QdrantStoreError(f"Cannot connect to Qdrant: {exc}") from exc

    def _ensure_collection(self) -> None:
        try:
            exists = self._client.collection_exists(self.collection_name)
        except Exception as exc:
            raise QdrantStoreError(
                f"Cannot reach Qdrant when checking collection: {exc}"
            ) from exc

        if exists:
            return

        logger.info(
            f"Creating Qdrant collection '{self.collection_name}' "
            f"(dense={self._dense_size}d, sparse=BM25 IDF)"
        )
        try:
            self._client.create_collection(
                collection_name=self.collection_name,
                vectors_config={
                    DENSE_VECTOR_NAME: models.VectorParams(
                        size=self._dense_size,
                        distance=models.Distance.COSINE,
                    ),
                },
                sparse_vectors_config={
                    SPARSE_VECTOR_NAME: models.SparseVectorParams(
                        modifier=models.Modifier.IDF,
                    ),
                },
            )
        except Exception as exc:
            raise QdrantStoreError(
                f"Failed to create collection '{self.collection_name}': {exc}"
            ) from exc

        # Add a payload index on metadata.doc_id so dedup scrolls/counts
        # are O(log n) instead of full scans. Skipped in embedded mode
        # (qdrant-client warns + ignores it there anyway).
        if self._backend_label.startswith("remote:"):
            try:
                self._client.create_payload_index(
                    collection_name=self.collection_name,
                    field_name="metadata.doc_id",
                    field_schema=models.PayloadSchemaType.KEYWORD,
                )
            except Exception as exc:
                logger.warning(f"Could not create payload index on doc_id: {exc}")

    def _doc_id_filter(self, doc_id: str) -> models.Filter:
        return models.Filter(
            must=[
                models.FieldCondition(
                    key="metadata.doc_id",
                    match=models.MatchValue(value=doc_id),
                )
            ]
        )
