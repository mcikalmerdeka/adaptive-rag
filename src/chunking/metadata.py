"""Metadata helpers for indexed chunks.

The chunk metadata is what makes retrieval *and* citations work later. We
keep the schema small and stable:

    {
      "doc_id":           sha256(file_bytes)[:16]   # stable across re-ingests
      "source":           absolute path of the original file
      "filename":         basename of the original file
      "header_path":      "h1 > h2 > h3" (empty for headerless content)
      "chunk_index":      int — 0-based position in the document
      "total_chunks":     int — total chunks generated for this doc
      "ingested_at":      ISO-8601 UTC timestamp
      "parser":           "docling" | "qwen3-vl" | "passthrough"
      "pages":            int | None  (only set for PDFs)
      "extension":        ".pdf" | ".docx" | ...  (debugging convenience)
    }

Anything else can live in a sibling DB later. We deliberately do NOT add
``access_level``, ``department``, ``tags`` until a feature actually needs them.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Deterministic UUID namespace used for chunk IDs. uuid5(NAMESPACE, key)
# always returns the same UUID for the same key, which means re-ingesting a
# document upserts (replaces) existing points instead of duplicating them.
CHUNK_ID_NAMESPACE = uuid.UUID("c1a8f6c0-5d2a-4d4c-8a4f-9d8d3e9b1a01")


def compute_doc_id(file_path: str | Path) -> str:
    """Stable 16-char hex id derived from the file's content hash."""
    path = Path(file_path)
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()[:16]


def chunk_uuid(doc_id: str, chunk_index: int) -> str:
    """Deterministic UUID for a (doc_id, chunk_index) pair."""
    return str(uuid.uuid5(CHUNK_ID_NAMESPACE, f"{doc_id}-{chunk_index}"))


def build_chunk_metadata(
    *,
    doc_id: str,
    source_path: str | Path,
    parser: str,
    pages: int | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the per-document portion of metadata. Per-chunk fields
    (``chunk_index``, ``total_chunks``, ``header_path``) are added by the
    chunker after it knows how many chunks were produced.
    """
    path = Path(source_path)
    base: dict[str, Any] = {
        "doc_id": doc_id,
        "source": str(path.absolute()),
        "filename": path.name,
        "extension": path.suffix.lower(),
        "parser": parser,
        "pages": pages,
        "ingested_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    if extra:
        base.update(extra)
    return base
