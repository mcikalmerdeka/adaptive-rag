"""SHA256-keyed disk cache for OCR results.

Each entry is a plain ``.md`` file named after the hex digest of the bytes
that were sent to the OCR engine. This makes the cache:

- Trivially debuggable (open the .md and read it).
- Safe to share across processes / users.
- Cheap to invalidate (delete the file).

Sized expectations: a typical scanned PDF page is ~5-15 KB of markdown,
so 10,000 cached pages ≈ 100 MB on disk. Acceptable for a portfolio project.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class OcrCache:
    """Content-hash cache for OCR markdown results."""

    def __init__(self, root: str | Path = ".cache/ocr") -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def key(content: bytes) -> str:
        return hashlib.sha256(content).hexdigest()

    def _path(self, key: str) -> Path:
        return self.root / f"{key}.md"

    def get(self, content: bytes) -> str | None:
        path = self._path(self.key(content))
        if not path.exists():
            return None
        try:
            return path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning(f"Cache read failed for {path.name}: {exc}")
            return None

    def put(self, content: bytes, markdown: str) -> None:
        path = self._path(self.key(content))
        try:
            path.write_text(markdown, encoding="utf-8")
        except OSError as exc:
            logger.warning(f"Cache write failed for {path.name}: {exc}")


