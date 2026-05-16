"""Tests for src.chunking.metadata — deterministic IDs and schema compliance."""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest

from src.chunking.metadata import (
    CHUNK_ID_NAMESPACE,
    build_chunk_metadata,
    chunk_uuid,
    compute_doc_id,
)


class TestComputeDocId:
    """Stable 16-char hex ID from file content hash."""

    def test_deterministic(self, tmp_path: Path) -> None:
        f = tmp_path / "doc.txt"
        f.write_text("hello world")
        id1 = compute_doc_id(f)
        id2 = compute_doc_id(f)
        assert id1 == id2
        assert len(id1) == 16

    def test_content_sensitive(self, tmp_path: Path) -> None:
        f1 = tmp_path / "a.txt"
        f1.write_text("alpha")
        f2 = tmp_path / "b.txt"
        f2.write_text("beta")
        assert compute_doc_id(f1) != compute_doc_id(f2)

    def test_hex_only(self, tmp_path: Path) -> None:
        f = tmp_path / "doc.txt"
        f.write_text("anything")
        doc_id = compute_doc_id(f)
        assert set(doc_id).issubset(set("0123456789abcdef"))

    def test_matches_sha256_prefix(self, tmp_path: Path) -> None:
        f = tmp_path / "doc.txt"
        content = b"predictable content"
        f.write_bytes(content)
        expected = hashlib.sha256(content).hexdigest()[:16]
        assert compute_doc_id(f) == expected


class TestChunkUuid:
    """Deterministic UUID5 from (doc_id, chunk_index)."""

    def test_deterministic(self) -> None:
        u1 = chunk_uuid("abc123", 0)
        u2 = chunk_uuid("abc123", 0)
        assert u1 == u2

    def test_different_index(self) -> None:
        u1 = chunk_uuid("abc123", 0)
        u2 = chunk_uuid("abc123", 1)
        assert u1 != u2

    def test_different_doc(self) -> None:
        u1 = chunk_uuid("abc123", 0)
        u2 = chunk_uuid("def456", 0)
        assert u1 != u2

    def test_valid_uuid(self) -> None:
        u = chunk_uuid("abc123", 0)
        parsed = uuid.UUID(u)
        assert str(parsed) == u

    def test_uses_namespace(self) -> None:
        u = chunk_uuid("abc123", 0)
        expected = str(uuid.uuid5(CHUNK_ID_NAMESPACE, "abc123-0"))
        assert u == expected


class TestBuildChunkMetadata:
    """Metadata schema completeness and defaults."""

    def test_required_fields(self, tmp_path: Path) -> None:
        f = tmp_path / "policy.pdf"
        f.write_text("dummy")
        meta = build_chunk_metadata(
            doc_id="deadbeef",
            source_path=f,
            parser="docling",
        )
        assert meta["doc_id"] == "deadbeef"
        assert meta["source"] == str(f.absolute())
        assert meta["filename"] == "policy.pdf"
        assert meta["extension"] == ".pdf"
        assert meta["parser"] == "docling"
        assert meta["pages"] is None
        assert "ingested_at" in meta

    def test_pages_override(self, tmp_path: Path) -> None:
        f = tmp_path / "report.pdf"
        f.write_text("dummy")
        meta = build_chunk_metadata(
            doc_id="abc",
            source_path=f,
            parser="qwen3-vl",
            pages=42,
        )
        assert meta["pages"] == 42

    def test_extra_fields(self, tmp_path: Path) -> None:
        f = tmp_path / "doc.txt"
        f.write_text("dummy")
        meta = build_chunk_metadata(
            doc_id="abc",
            source_path=f,
            parser="passthrough",
            extra={"author": "tester", "department": "qa"},
        )
        assert meta["author"] == "tester"
        assert meta["department"] == "qa"

    def test_ingested_at_iso_format(self, tmp_path: Path) -> None:
        f = tmp_path / "doc.txt"
        f.write_text("dummy")
        meta = build_chunk_metadata(
            doc_id="abc",
            source_path=f,
            parser="passthrough",
        )
        ingested = meta["ingested_at"]
        assert ingested.endswith("+00:00") or "Z" in ingested or "T" in ingested
