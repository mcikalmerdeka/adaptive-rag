"""Tests for src.cache.embedding_cache — disk persistence, hit/miss, namespace isolation."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.cache.embedding_cache import _CachedEmbeddings, cached_embeddings


class TestCachedEmbeddingsKey:
    """Keys must be deterministic and namespace-isolated."""

    def test_key_deterministic(self, tmp_path: Path) -> None:
        mock = MagicMock(spec=["embed_documents", "embed_query"])
        cache = _CachedEmbeddings(mock, namespace="ns1", cache_dir=tmp_path)
        k1 = cache._key("hello")
        k2 = cache._key("hello")
        assert k1 == k2

    def test_key_namespace_sensitive(self, tmp_path: Path) -> None:
        mock = MagicMock(spec=["embed_documents", "embed_query"])
        c1 = _CachedEmbeddings(mock, namespace="ns1", cache_dir=tmp_path)
        c2 = _CachedEmbeddings(mock, namespace="ns2", cache_dir=tmp_path)
        assert c1._key("hello") != c2._key("hello")

    def test_key_text_sensitive(self, tmp_path: Path) -> None:
        mock = MagicMock(spec=["embed_documents", "embed_query"])
        cache = _CachedEmbeddings(mock, namespace="ns1", cache_dir=tmp_path)
        assert cache._key("hello") != cache._key("world")


class TestCachedEmbeddingsReadWrite:
    """Round-trip a vector through the disk cache."""

    def test_write_and_read(self, tmp_path: Path) -> None:
        mock = MagicMock(spec=["embed_documents", "embed_query"])
        cache = _CachedEmbeddings(mock, namespace="ns1", cache_dir=tmp_path)
        vec = [0.1, 0.2, 0.3]
        cache._write("text", vec)
        loaded = cache._read("text")
        assert loaded == pytest.approx(vec)

    def test_read_miss(self, tmp_path: Path) -> None:
        mock = MagicMock(spec=["embed_documents", "embed_query"])
        cache = _CachedEmbeddings(mock, namespace="ns1", cache_dir=tmp_path)
        assert cache._read("never_written") is None

    def test_file_created(self, tmp_path: Path) -> None:
        mock = MagicMock(spec=["embed_documents", "embed_query"])
        cache = _CachedEmbeddings(mock, namespace="ns1", cache_dir=tmp_path)
        cache._write("x", [1.0])
        assert cache._path("x").exists()

    def test_namespace_isolation_on_disk(self, tmp_path: Path) -> None:
        mock = MagicMock(spec=["embed_documents", "embed_query"])
        c1 = _CachedEmbeddings(mock, namespace="ns1", cache_dir=tmp_path)
        c2 = _CachedEmbeddings(mock, namespace="ns2", cache_dir=tmp_path)
        c1._write("text", [1.0, 2.0])
        assert c1._read("text") is not None
        assert c2._read("text") is None


class TestCachedEmbeddingsQuery:
    """embed_query delegates to the underlying model on miss, returns cache on hit."""

    def test_miss_calls_underlying(self, tmp_path: Path) -> None:
        mock = MagicMock(spec=["embed_documents", "embed_query"])
        mock.embed_query.return_value = [0.5, 0.5]
        cache = _CachedEmbeddings(mock, namespace="ns", cache_dir=tmp_path)

        result = cache.embed_query("hello")
        assert result == [0.5, 0.5]
        mock.embed_query.assert_called_once_with("hello")

    def test_hit_skips_underlying(self, tmp_path: Path) -> None:
        mock = MagicMock(spec=["embed_documents", "embed_query"])
        mock.embed_query.return_value = [0.9, 0.1]
        cache = _CachedEmbeddings(mock, namespace="ns", cache_dir=tmp_path)

        # First call — miss, writes cache
        cache.embed_query("hello")
        mock.embed_query.assert_called_once()

        # Second call — hit, should not call underlying again
        mock.reset_mock()
        result = cache.embed_query("hello")
        # float32 round-trip loses a little precision; use approx
        assert result == pytest.approx([0.9, 0.1])
        mock.embed_query.assert_not_called()


class TestCachedEmbeddingsDocuments:
    """embed_documents batches hits and misses correctly."""

    def test_all_hits(self, tmp_path: Path) -> None:
        mock = MagicMock(spec=["embed_documents", "embed_query"])
        cache = _CachedEmbeddings(mock, namespace="ns", cache_dir=tmp_path)
        # Pre-seed cache
        cache._write("a", [1.0])
        cache._write("b", [2.0])

        mock.reset_mock()
        result = cache.embed_documents(["a", "b"])
        assert result == [[1.0], [2.0]]
        mock.embed_documents.assert_not_called()

    def test_all_misses(self, tmp_path: Path) -> None:
        mock = MagicMock(spec=["embed_documents", "embed_query"])
        mock.embed_documents.return_value = [[1.0], [2.0]]
        cache = _CachedEmbeddings(mock, namespace="ns", cache_dir=tmp_path)

        result = cache.embed_documents(["a", "b"])
        assert result == [[1.0], [2.0]]
        mock.embed_documents.assert_called_once_with(["a", "b"])

    def test_mixed_hit_miss(self, tmp_path: Path) -> None:
        mock = MagicMock(spec=["embed_documents", "embed_query"])
        mock.embed_documents.return_value = [[2.0]]
        cache = _CachedEmbeddings(mock, namespace="ns", cache_dir=tmp_path)
        cache._write("a", [1.0])

        result = cache.embed_documents(["a", "b"])
        assert result == [[1.0], [2.0]]
        mock.embed_documents.assert_called_once_with(["b"])


class TestCachedEmbeddingsFactory:
    """``cached_embeddings`` returns an ``Embeddings`` wrapper."""

    def test_returns_cached_embeddings(self, tmp_path: Path) -> None:
        mock = MagicMock(spec=["embed_documents", "embed_query"])
        result = cached_embeddings(mock, namespace="ns", cache_dir=tmp_path)
        assert isinstance(result, _CachedEmbeddings)
