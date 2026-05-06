"""Header-aware markdown chunker.

Two-pass strategy:

1. ``MarkdownHeaderTextSplitter`` cuts on ``#``, ``##``, ``###`` so chunks
   respect the document's semantic structure. The header path
   (e.g. ``"Refund Policy > Eligibility"``) is captured into metadata.
2. Any header section that exceeds ``max_chunk_size`` is further split with
   ``RecursiveCharacterTextSplitter``. Sub-chunks inherit the parent header
   path so retrieval can still surface the right context.

Headers are kept *inside* the chunk content (``strip_headers=False``) so the
embedding model sees them — this materially helps retrieval recall on
header-sensitive queries.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from langchain_core.documents import Document
from langchain_text_splitters import (
    MarkdownHeaderTextSplitter,
    RecursiveCharacterTextSplitter,
)

logger = logging.getLogger(__name__)

DEFAULT_HEADERS: list[tuple[str, str]] = [
    ("#", "h1"),
    ("##", "h2"),
    ("###", "h3"),
]


@dataclass
class ChunkingConfig:
    max_chunk_size: int = 1500
    chunk_overlap: int = 200
    headers: list[tuple[str, str]] | None = None

    def header_pairs(self) -> list[tuple[str, str]]:
        return self.headers or DEFAULT_HEADERS


class MarkdownChunker:
    """Split markdown into header-aware chunks with rich metadata."""

    def __init__(self, config: ChunkingConfig | None = None) -> None:
        self.config = config or ChunkingConfig()
        self._header_splitter = MarkdownHeaderTextSplitter(
            headers_to_split_on=self.config.header_pairs(),
            strip_headers=False,
        )
        self._char_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.config.max_chunk_size,
            chunk_overlap=self.config.chunk_overlap,
            separators=["\n\n", "\n", ". ", " ", ""],
        )

    # ---- public API ----------------------------------------------------

    def chunk(
        self,
        markdown: str,
        base_metadata: dict[str, Any],
    ) -> list[Document]:
        """Return a list of ``Document`` chunks. Empty input → empty list."""
        if not markdown or not markdown.strip():
            return []

        header_chunks = self._header_splitter.split_text(markdown)
        if not header_chunks:
            # No headers detected — treat the entire doc as a single section.
            header_chunks = [Document(page_content=markdown, metadata={})]

        documents: list[Document] = []
        for hc in header_chunks:
            header_path = self._extract_header_path(hc.metadata)

            if len(hc.page_content) <= self.config.max_chunk_size:
                documents.append(
                    Document(
                        page_content=hc.page_content,
                        metadata={**base_metadata, "header_path": header_path},
                    )
                )
                continue

            # Section too large — split further.
            sub_texts = self._char_splitter.split_text(hc.page_content)
            for sub_text in sub_texts:
                documents.append(
                    Document(
                        page_content=sub_text,
                        metadata={**base_metadata, "header_path": header_path},
                    )
                )

        # Inject chunk_index / total_chunks now that we know the count.
        total = len(documents)
        for i, doc in enumerate(documents):
            doc.metadata["chunk_index"] = i
            doc.metadata["total_chunks"] = total

        logger.info(
            f"Chunked '{base_metadata.get('filename', '?')}' → "
            f"{total} chunks "
            f"(avg {self._avg_len(documents)} chars)"
        )
        return documents

    # ---- helpers -------------------------------------------------------

    @staticmethod
    def _extract_header_path(metadata: dict[str, Any]) -> str:
        """Turn ``{'h1': 'Foo', 'h2': 'Bar'}`` into ``'Foo > Bar'``."""
        ordered_keys = sorted(
            (k for k in metadata if k.startswith("h") and k[1:].isdigit()),
            key=lambda k: int(k[1:]),
        )
        return " > ".join(metadata[k] for k in ordered_keys if metadata[k])

    @staticmethod
    def _avg_len(docs: list[Document]) -> int:
        if not docs:
            return 0
        return sum(len(d.page_content) for d in docs) // len(docs)
