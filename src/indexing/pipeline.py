"""End-to-end ingestion pipeline.

Wraps the convert → chunk → upsert flow into one call so the UI and CLI
have a single entrypoint. Handles deduplication, progress callbacks and
error reporting.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from src.chunking import (
    MarkdownChunker,
    build_chunk_metadata,
    compute_doc_id,
)
from src.chunking.markdown_chunker import ChunkingConfig
from src.core import ConversionOutput, MarkdownConverterService

from .qdrant_store import QdrantStore

logger = logging.getLogger(__name__)


@dataclass
class IngestionResult:
    file_path: Path
    doc_id: str
    parser: str
    pages: int | None
    chunks_created: int
    chunks_indexed: int
    skipped: bool  # True if doc was already present and replace=False
    markdown_chars: int


class IngestionPipeline:
    """convert → chunk → embed → upsert."""

    def __init__(
        self,
        converter: MarkdownConverterService | None = None,
        chunker: MarkdownChunker | None = None,
        store: QdrantStore | None = None,
        chunking_config: ChunkingConfig | None = None,
    ) -> None:
        self._converter = converter or MarkdownConverterService()
        self._chunker = chunker or MarkdownChunker(chunking_config)
        # Lazy: don't build the Qdrant client unless we actually ingest.
        self._store_override = store
        self._store: QdrantStore | None = store

    @property
    def store(self) -> QdrantStore:
        if self._store is None:
            self._store = QdrantStore()
        return self._store

    def ingest(
        self,
        file_path: str | Path,
        *,
        force_qwen_for_pdf: bool = False,
        replace_existing: bool = True,
        skip_if_exists: bool = False,
        ocr_progress: Callable[[int, int], None] | None = None,
    ) -> IngestionResult:
        path = Path(file_path)
        doc_id = compute_doc_id(path)

        # Fast-path: skip if requested and already indexed.
        if skip_if_exists and self.store.doc_exists(doc_id):
            existing = self.store.count_chunks_for_doc(doc_id)
            logger.info(
                f"Skipping {path.name}: doc_id={doc_id} already has "
                f"{existing} chunks (skip_if_exists=True)"
            )
            return IngestionResult(
                file_path=path,
                doc_id=doc_id,
                parser="-",
                pages=None,
                chunks_created=0,
                chunks_indexed=0,
                skipped=True,
                markdown_chars=0,
            )

        # Convert.
        output: ConversionOutput = self._converter.convert_detailed(
            path,
            force_qwen_for_pdf=force_qwen_for_pdf,
            progress=ocr_progress,
        )
        if not output.markdown.strip():
            logger.warning(f"{path.name}: empty markdown, nothing to index")
            return IngestionResult(
                file_path=path,
                doc_id=doc_id,
                parser=output.parser,
                pages=output.pages,
                chunks_created=0,
                chunks_indexed=0,
                skipped=False,
                markdown_chars=0,
            )

        # Chunk.
        base_meta = build_chunk_metadata(
            doc_id=doc_id,
            source_path=path,
            parser=output.parser,
            pages=output.pages,
        )
        chunks = self._chunker.chunk(output.markdown, base_meta)

        if not chunks:
            return IngestionResult(
                file_path=path,
                doc_id=doc_id,
                parser=output.parser,
                pages=output.pages,
                chunks_created=0,
                chunks_indexed=0,
                skipped=False,
                markdown_chars=len(output.markdown),
            )

        # Upsert.
        n_indexed = self.store.upsert_chunks(
            chunks,
            doc_id=doc_id,
            replace_existing=replace_existing,
        )

        return IngestionResult(
            file_path=path,
            doc_id=doc_id,
            parser=output.parser,
            pages=output.pages,
            chunks_created=len(chunks),
            chunks_indexed=n_indexed,
            skipped=False,
            markdown_chars=len(output.markdown),
        )
