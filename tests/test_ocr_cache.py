"""Tests for src.cache.ocr_cache — SHA256 keying, hit/miss, disk I/O."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.cache.ocr_cache import OcrCache


class TestOcrCacheKey:
    """Key generation is pure SHA256 of the raw bytes."""

    def test_key_deterministic(self) -> None:
        content = b"same content"
        assert OcrCache.key(content) == OcrCache.key(content)

    def test_key_content_sensitive(self) -> None:
        assert OcrCache.key(b"a") != OcrCache.key(b"b")

    def test_key_length(self) -> None:
        assert len(OcrCache.key(b"x")) == 64  # SHA256 hex


class TestOcrCacheHitMiss:
    """get / put round-trips through the filesystem."""

    def test_miss_on_empty_cache(self, tmp_path: Path) -> None:
        cache = OcrCache(tmp_path / "ocr")
        assert cache.get(b"unknown") is None

    def test_put_and_get(self, tmp_path: Path) -> None:
        cache = OcrCache(tmp_path / "ocr")
        content = b"page image bytes"
        cache.put(content, "# Markdown\n")
        assert cache.get(content) == "# Markdown\n"

    def test_put_overwrites(self, tmp_path: Path) -> None:
        cache = OcrCache(tmp_path / "ocr")
        content = b"same"
        cache.put(content, "v1")
        cache.put(content, "v2")
        assert cache.get(content) == "v2"

    def test_different_content_different_files(self, tmp_path: Path) -> None:
        cache = OcrCache(tmp_path / "ocr")
        c1 = b"page 1"
        c2 = b"page 2"
        cache.put(c1, "md1")
        cache.put(c2, "md2")
        assert cache.get(c1) == "md1"
        assert cache.get(c2) == "md2"

    def test_file_extension(self, tmp_path: Path) -> None:
        cache = OcrCache(tmp_path / "ocr")
        content = b"x"
        key = cache.key(content)
        cache.put(content, "text")
        assert (cache.root / f"{key}.md").exists()

    def test_directory_created(self, tmp_path: Path) -> None:
        root = tmp_path / "nested" / "ocr"
        assert not root.exists()
        cache = OcrCache(root)
        assert root.is_dir()
