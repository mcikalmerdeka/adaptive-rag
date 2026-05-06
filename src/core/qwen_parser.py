"""Qwen3-VL OCR parser.

Extracts markdown from images and scanned PDF pages by calling DashScope's
OpenAI-compatible Qwen3-VL endpoint. Results are cached on disk by SHA256 of
the image bytes to avoid burning API credits on re-runs.
"""

from __future__ import annotations

import base64
import logging
from collections.abc import Callable, Iterable
from pathlib import Path

from openai import APIConnectionError, APIError, OpenAI, RateLimitError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.cache import OcrCache
from src.config import settings
from src.utils import iter_pdf_page_pngs

logger = logging.getLogger(__name__)


# Deterministic prompt: explicit, no creativity, no commentary.
OCR_PROMPT = (
    "Extract all text from this image into clean GitHub-Flavored Markdown.\n"
    "Rules:\n"
    "- Preserve the heading hierarchy using #, ##, ###.\n"
    "- Render tables using pipe (|) syntax with a separator row.\n"
    "- Preserve bullet and numbered lists.\n"
    "- Do not summarize, paraphrase, or add commentary.\n"
    "- Do not wrap the entire output in a code fence.\n"
    "- If a region is illegible, write [illegible] in its place.\n"
    "- Output the markdown only. No preamble, no explanation."
)

DEFAULT_MODEL = "qwen3-vl-plus"
DEFAULT_BASE_URL = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"

_RETRYABLE = (RateLimitError, APIConnectionError, APIError)


class QwenParserError(Exception):
    """Raised when Qwen OCR fails after retries."""


class QwenParser:
    """Wrap Qwen3-VL OCR with disk caching and retry."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = DEFAULT_MODEL,
        base_url: str = DEFAULT_BASE_URL,
        cache: OcrCache | None = None,
    ) -> None:
        api_key = api_key or settings.QWEN_API_KEY
        if not api_key:
            raise QwenParserError(
                "QWEN_API_KEY is not set. Add it to .env or pass api_key=..."
            )

        self._client = OpenAI(api_key=api_key, base_url=base_url)
        self._model = model
        self._cache = cache or OcrCache(settings.CACHE_DIR / "ocr")

    # ---- public API -----------------------------------------------------

    def extract_image(self, file_path: str | Path) -> str:
        path = Path(file_path)
        image_bytes = path.read_bytes()
        suffix = path.suffix.lstrip(".").lower() or "png"
        return self._extract_from_bytes(image_bytes, mime_suffix=suffix, label=path.name)

    def extract_pdf_pages(
        self,
        file_path: str | Path,
        progress: Callable[[int, int], None] | None = None,
    ) -> str:
        """Render each page to PNG and OCR via Qwen. Concatenate results.

        ``progress(current, total)`` is invoked after each page completes
        (cached or freshly OCR'd). Useful for UI feedback.
        """
        path = Path(file_path)
        pages = list(iter_pdf_page_pngs(path))
        total = len(pages)
        if total == 0:
            return ""

        rendered: list[str] = []
        for i, png_bytes in pages:
            label = f"{path.name} page {i}/{total}"
            md = self._extract_from_bytes(png_bytes, mime_suffix="png", label=label)
            rendered.append(self._format_page_block(i, md))
            if progress is not None:
                progress(i, total)

        return "\n\n".join(rendered).strip()

    # ---- internals ------------------------------------------------------

    def _extract_from_bytes(
        self,
        content: bytes,
        mime_suffix: str,
        label: str,
    ) -> str:
        cached = self._cache.get(content)
        if cached is not None:
            logger.info(f"OCR cache hit: {label}")
            return cached

        logger.info(f"OCR miss → calling Qwen: {label}")
        markdown = self._call_qwen(content, mime_suffix)
        self._cache.put(content, markdown)
        return markdown

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(_RETRYABLE),
        reraise=True,
    )
    def _call_qwen(self, content: bytes, mime_suffix: str) -> str:
        b64 = base64.b64encode(content).decode("utf-8")
        data_url = f"data:image/{mime_suffix};base64,{b64}"

        try:
            completion = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "image_url", "image_url": {"url": data_url}},
                            {"type": "text", "text": OCR_PROMPT},
                        ],
                    }
                ],
            )
        except _RETRYABLE:
            raise
        except Exception as exc:
            raise QwenParserError(f"Qwen request failed: {exc}") from exc

        text = (completion.choices[0].message.content or "").strip()
        return self._strip_outer_fence(text)

    @staticmethod
    def _strip_outer_fence(text: str) -> str:
        """Some VLMs wrap the whole response in ```markdown ... ``` despite the prompt.

        Strip a single outer fence if present, but leave inner fences alone.
        """
        if not text.startswith("```"):
            return text

        lines = text.splitlines()
        if not lines[-1].strip().startswith("```"):
            return text

        first = lines[0].strip()
        if first in {"```", "```markdown", "```md"}:
            return "\n".join(lines[1:-1]).strip()
        return text

    @staticmethod
    def _format_page_block(page_number: int, markdown: str) -> str:
        if not markdown:
            return f"<!-- page {page_number}: empty -->"
        return f"<!-- page {page_number} -->\n\n{markdown}"

    # ---- helpers --------------------------------------------------------

    @staticmethod
    def is_configured() -> bool:
        return bool(settings.QWEN_API_KEY)

    def warm_up(self) -> None:
        """Sanity-ping. Does not call the model — just verifies client init."""
        _ = self._client  # ensure created

    @property
    def supported_image_suffixes(self) -> Iterable[str]:
        return ("png", "jpg", "jpeg", "webp")
