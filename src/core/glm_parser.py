"""GLM-5.3-Flash vision parser (Z.ai PAAS v4).

Extracts markdown from images, scanned PDF pages, and videos by calling
Z.ai's OpenAI-compatible chat completion endpoint. Results are cached on
disk by SHA256 of the exact bytes sent to the API, so re-ingesting the
same input never re-calls the model.

References:
- Spec: docs/superpowers/specs/2026-10-12-glm-5.3-flash-migration-design.md
- API reference: https://docs.z.ai/api-reference/llm/chat-completion
- Model guide: https://docs.z.ai/guides/vlm/glm-5.3-flash
"""

from __future__ import annotations

import base64
import io
import logging
from pathlib import Path

from openai import APIConnectionError, APIError, OpenAI, RateLimitError
from PIL import Image
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.cache import OcrCache
from src.config import settings

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

VIDEO_PROMPT = (
    "Produce a complete markdown record of this video.\n"
    "Rules:\n"
    "- Split the record into '## [mm:ss]' sections, one per distinct scene, "
    "event, or topic shift, in chronological order.\n"
    "- Transcribe spoken dialogue as bullet quotes, attributing the speaker "
    "by name or role when identifiable.\n"
    "- Capture all on-screen text, captions, and overlays.\n"
    "- Describe notable visuals (people, actions, settings, products) "
    "concisely but completely.\n"
    "- Do not add commentary, review, or opinion.\n"
    "- Do not wrap the entire output in a code fence.\n"
    "- If speech is inaudible, write [inaudible] in its place.\n"
    "- Output the markdown only. No preamble, no explanation."
)

_RETRYABLE = (RateLimitError, APIConnectionError, APIError)

# Z.ai image limits: <=5 MB per image, pixels not exceeding 6000*6000, and
# only jpg/png/jpeg are documented. Base64 inflates by ~x1.33, so act on
# raw bytes over 4.5 MB rather than waiting for the API to refuse.
_IMAGE_PASSTHROUGH = {"jpg", "jpeg", "png"}
_IMAGE_MAX_SIDE = 6000
_IMAGE_RAW_LIMIT = int(4.5 * 1024 * 1024)


class GLMParserError(Exception):
    """Raised when GLM vision extraction fails after retries (or pre-flight)."""


class GLMParser:
    """GLM-5.3-Flash vision extraction with disk caching and retry."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        reasoning_effort: str | None = None,
        cache: OcrCache | None = None,
    ) -> None:
        api_key = api_key or settings.ZAI_API_KEY
        if not api_key:
            raise GLMParserError(
                "ZAI_API_KEY is not set. Add it to .env or pass api_key=..."
            )

        self._client = OpenAI(
            api_key=api_key,
            base_url=base_url or settings.ZAI_BASE_URL,
            default_headers={"Accept-Language": "en-US,en"},
        )
        self._model = model or settings.GLM_MODEL
        self._reasoning_effort = reasoning_effort or settings.GLM_REASONING_EFFORT
        self._cache = cache or OcrCache(settings.CACHE_DIR / "ocr")

    @property
    def model_name(self) -> str:
        """Resolved model code — used as parser provenance in metadata."""
        return self._model

    # ---- public API ------------------------------------------------------

    def extract_image(self, file_path: str | Path) -> str:
        path = Path(file_path)
        suffix = path.suffix.lstrip(".").lower() or "png"
        data, mime = self._prepare_image(path.read_bytes(), suffix)
        return self._extract_from_bytes(data, mime, label=path.name)

    # ---- internals -------------------------------------------------------

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

        logger.info(f"OCR miss → calling {self._model}: {label}")
        markdown = self._call_glm(content, mime_suffix)
        self._cache.put(content, markdown)
        return markdown

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(_RETRYABLE),
        reraise=True,
    )
    def _call_glm(self, content: bytes, mime_suffix: str) -> str:
        b64 = base64.b64encode(content).decode("ascii")
        data_url = f"data:image/{mime_suffix};base64,{b64}"
        blocks = [
            {"type": "image_url", "image_url": {"url": data_url}},
            {"type": "text", "text": OCR_PROMPT},
        ]

        try:
            completion = self._client.chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": blocks}],
                # Z.ai recommended settings for GLM-5.3-Flash.
                temperature=1.0,
                top_p=0.95,
                reasoning_effort=self._reasoning_effort,
                max_tokens=settings.GLM_MAX_TOKENS,
            )
        except _RETRYABLE:
            raise
        except Exception as exc:
            raise GLMParserError(f"GLM request failed: {exc}") from exc

        text = (completion.choices[0].message.content or "").strip()
        return self._strip_outer_fence(text)

    def _prepare_image(self, raw: bytes, mime_suffix: str) -> tuple[bytes, str]:
        """Return ``(bytes_to_send, mime_suffix)`` within Z.ai's image limits.

        jpg/jpeg/png within limits pass through untouched; anything else
        (e.g. webp, which Z.ai does not document) or anything oversized is
        re-encoded to JPEG q90 with the long side capped at 6000. Pillow
        inspection is best effort: unreadable bytes are forwarded as-is so
        the API, not us, reports the refusal.
        """
        if mime_suffix.lower() not in _IMAGE_PASSTHROUGH:
            try:
                with Image.open(io.BytesIO(raw)) as img:
                    return self._reencode(img), "jpeg"
            except Exception:
                return raw, mime_suffix

        try:
            with Image.open(io.BytesIO(raw)) as img:
                within_limits = (
                    len(raw) <= _IMAGE_RAW_LIMIT and max(img.size) <= _IMAGE_MAX_SIDE
                )
                if within_limits:
                    return raw, mime_suffix
                img.load()
                return self._reencode(img), "jpeg"
        except Exception:
            return raw, mime_suffix

    @staticmethod
    def _reencode(img: Image.Image) -> bytes:
        """Downscale to the 6000 px cap when needed and save as JPEG q90."""
        scale = _IMAGE_MAX_SIDE / max(img.size)
        if scale < 1:
            img = img.resize(
                (max(1, round(img.width * scale)), max(1, round(img.height * scale)))
            )
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=90)
        return buf.getvalue()

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

    # ---- helpers ---------------------------------------------------------

    @staticmethod
    def is_configured() -> bool:
        return bool(settings.ZAI_API_KEY)
