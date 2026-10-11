"""Tests for src.core.glm_parser — mocked OpenAI client, no network."""

from __future__ import annotations

import base64
import io
import os
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from openai import APIConnectionError

import src.core.glm_parser as glm_parser_module
from src.cache.ocr_cache import OcrCache
from src.core.glm_parser import GLMParser, GLMParserError


def _fake_settings(**overrides):
    """Replace the module-level settings handle for full test control."""
    base = dict(
        ZAI_API_KEY="test-key",
        ZAI_BASE_URL="https://api.z.ai/api/paas/v4/",
        GLM_MODEL="glm-5.3-flash",
        GLM_REASONING_EFFORT="low",
        GLM_MAX_TOKENS=8192,
        GLM_VIDEO_MAX_UPLOAD_MB=20,
        CACHE_DIR=Path("./.cache"),
    )
    base.update(overrides)
    return SimpleNamespace(**base)


class _FakeCompletions:
    def __init__(self, outcomes):
        self._outcomes = list(outcomes)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=outcome))]
        )


def _client_with(outcomes) -> tuple[object, _FakeCompletions]:
    fake = _FakeCompletions(outcomes)
    return SimpleNamespace(chat=SimpleNamespace(completions=fake)), fake


def _conn_error() -> APIConnectionError:
    # openai >=2.33 made both parameters keyword-only.
    return APIConnectionError(request=httpx.Request("POST", "https://api.z.ai/"))


def _bad_request_error(message: str) -> Exception:
    """A real 4xx rejection, mirroring Z.ai's error taxonomy.

    Every openai SDK exception subclasses APIError, so a genuine payload
    rejection arrives as BadRequestError — not ValueError.
    """
    from openai import BadRequestError

    return BadRequestError(
        message,
        response=httpx.Response(
            400, request=httpx.Request("POST", "https://api.z.ai/api/paas/v4/chat/completions")
        ),
        body={"error": {"message": message}},
    )


@pytest.fixture
def parser(monkeypatch, tmp_path):
    """GLMParser with fake settings + fake client injected."""
    monkeypatch.setattr(glm_parser_module, "settings", _fake_settings())
    parser = GLMParser(cache=OcrCache(tmp_path / "ocr"))
    client, fake = _client_with(["# Extracted\n\nmarkdown"])
    parser._client = client
    return parser, fake


class TestImageExtraction:
    def test_extract_image_sends_image_data_url_block(self, parser, tmp_path):
        p, fake = parser
        png = tmp_path / "doc.png"
        png.write_bytes(b"\x89PNG-fake-bytes")
        out = p.extract_image(png)
        assert out == "# Extracted\n\nmarkdown"
        assert len(fake.calls) == 1
        kwargs = fake.calls[0]
        b64 = base64.b64encode(b"\x89PNG-fake-bytes").decode()
        block = kwargs["messages"][0]["content"][0]
        assert block == {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}
        assert kwargs["messages"][0]["content"][1]["text"].startswith("Extract all text")
        assert kwargs["model"] == "glm-5.3-flash"
        assert kwargs["temperature"] == 1.0
        assert kwargs["top_p"] == 0.95
        assert kwargs["reasoning_effort"] == "low"
        assert kwargs["max_tokens"] == 8192

    def test_extract_image_webp_normalized(self, parser, tmp_path):
        from PIL import Image

        p, fake = parser
        webp = tmp_path / "doc.webp"
        Image.new("RGB", (20, 10), "white").save(webp, format="WEBP")
        p.extract_image(webp)
        url = fake.calls[0]["messages"][0]["content"][0]["image_url"]["url"]
        assert url.startswith("data:image/jpeg;base64,")
        assert "webp" not in url.split(",", 1)[0]

    def test_extract_image_cache_hit_skips_api(self, parser, tmp_path):
        p, fake = parser
        png = tmp_path / "doc.png"
        png.write_bytes(b"\x89PNG-fake-bytes")
        first = p.extract_image(png)
        second = p.extract_image(png)
        assert first == second == "# Extracted\n\nmarkdown"
        assert len(fake.calls) == 1

    def test_extract_image_strips_outer_fence(self, parser, tmp_path):
        p, fake = parser
        fake._outcomes = ["```markdown\n# Head\n```"]
        png = tmp_path / "doc.png"
        png.write_bytes(b"\x89PNG")
        assert p.extract_image(png) == "# Head"

    def test_retry_succeeds_on_transient_errors(self, tmp_path, monkeypatch):
        monkeypatch.setattr(glm_parser_module, "settings", _fake_settings())
        parser = GLMParser(cache=OcrCache(tmp_path / "ocr"))
        client, fake = _client_with([_conn_error(), _conn_error(), "ok"])
        parser._client = client
        png = tmp_path / "doc.png"
        png.write_bytes(b"x")
        assert parser.extract_image(png) == "ok"
        assert len(fake.calls) == 3

    def test_retry_exhausted_reraises(self, tmp_path, monkeypatch):
        monkeypatch.setattr(glm_parser_module, "settings", _fake_settings())
        parser = GLMParser(cache=OcrCache(tmp_path / "ocr"))
        client, fake = _client_with([_conn_error(), _conn_error(), _conn_error()])
        parser._client = client
        png = tmp_path / "doc.png"
        png.write_bytes(b"x")
        with pytest.raises(APIConnectionError):
            parser.extract_image(png)

    def test_non_retryable_error_wrapped(self, parser, tmp_path):
        p, fake = parser
        fake._outcomes = [_bad_request_error("bad image")]
        png = tmp_path / "doc.png"
        png.write_bytes(b"x")
        with pytest.raises(GLMParserError, match="bad image"):
            p.extract_image(png)
        assert len(fake.calls) == 1  # deterministic 4xx: never retried


class TestNormalization:
    def test_over_6000px_downscaled(self, tmp_path):
        from PIL import Image

        parser = GLMParser(api_key="k", cache=OcrCache(tmp_path / "ocr"))
        buf = io.BytesIO()
        Image.new("RGB", (6001, 10), "white").save(buf, format="PNG")
        data, mime = parser._prepare_image(buf.getvalue(), "png")
        img = Image.open(io.BytesIO(data))
        assert max(img.size) == 6000
        assert mime == "jpeg"

    def test_over_5mb_reencoded(self, tmp_path):
        from PIL import Image

        parser = GLMParser(api_key="k", cache=OcrCache(tmp_path / "ocr"))
        noise = os.urandom(1500 * 1500 * 3)
        buf = io.BytesIO()
        Image.frombytes("RGB", (1500, 1500), noise).save(buf, format="PNG")
        data, mime = parser._prepare_image(buf.getvalue(), "png")
        assert len(data) < buf.tell()
        assert mime == "jpeg"

    def test_small_jpeg_passthrough(self, tmp_path):
        from PIL import Image

        parser = GLMParser(api_key="k", cache=OcrCache(tmp_path / "ocr"))
        buf = io.BytesIO()
        Image.new("RGB", (10, 10), "white").save(buf, format="JPEG")
        raw = buf.getvalue()
        data, mime = parser._prepare_image(raw, "jpeg")
        assert data == raw and mime == "jpeg"

    def test_reencode_bakes_exif_orientation(self, tmp_path):
        from PIL import Image

        parser = GLMParser(api_key="k", cache=OcrCache(tmp_path / "ocr"))
        buf = io.BytesIO()
        img = Image.new("RGB", (2400, 3200), "white")
        exif = Image.Exif()
        exif[274] = 6  # portrait shot: display requires a 90° CW rotation
        img.save(buf, format="JPEG", exif=exif.tobytes())
        sideways = Image.open(io.BytesIO(buf.getvalue()))
        data = parser._reencode(sideways)
        assert Image.open(io.BytesIO(data)).size == (3200, 2400)


class TestConfig:
    def test_model_name_exposes_resolved_model(self, parser):
        p, _ = parser
        assert p.model_name == "glm-5.3-flash"

    def test_missing_key_raises(self, monkeypatch, tmp_path):
        monkeypatch.setattr(glm_parser_module, "settings", _fake_settings(ZAI_API_KEY=None))
        with pytest.raises(GLMParserError, match="ZAI_API_KEY"):
            GLMParser(cache=OcrCache(tmp_path / "ocr"))

    def test_is_configured(self, monkeypatch):
        monkeypatch.setattr(glm_parser_module, "settings", _fake_settings())
        assert GLMParser.is_configured() is True
        monkeypatch.setattr(glm_parser_module, "settings", _fake_settings(ZAI_API_KEY=None))
        assert GLMParser.is_configured() is False


class TestPdfPages:
    def test_per_page_blocks_and_progress(self, parser, monkeypatch):
        p, fake = parser
        pages = iter([(1, b"png-one"), (2, b"png-two")])
        monkeypatch.setattr(glm_parser_module, "iter_pdf_page_pngs", lambda path: pages)
        fake._outcomes = ["page one md", "page two md"]
        seen = []
        out = p.extract_pdf_pages(Path("scan.pdf"), progress=lambda c, t: seen.append((c, t)))
        assert "<!-- page 1 -->" in out and "<!-- page 2 -->" in out
        assert "page one md" in out and "page two md" in out
        assert seen == [(1, 2), (2, 2)]
        assert len(fake.calls) == 2
        assert fake.calls[0]["messages"][0]["content"][0]["image_url"]["url"].endswith(
            base64.b64encode(b"png-one").decode()
        )


class TestVideo:
    def test_video_size_guard_blocks_oversized(self, tmp_path, monkeypatch):
        monkeypatch.setattr(glm_parser_module, "settings", _fake_settings(GLM_VIDEO_MAX_UPLOAD_MB=1))
        parser = GLMParser(cache=OcrCache(tmp_path / "ocr"))
        client, fake = _client_with(["never called"])
        parser._client = client
        big = tmp_path / "movie.mp4"
        big.write_bytes(b"\0" * (2 * 1024 * 1024))
        with pytest.raises(GLMParserError, match="GLM_VIDEO_MAX_UPLOAD_MB"):
            parser.extract_video(big)
        assert fake.calls == []

    def test_extract_video_builds_video_data_url_block(self, parser, tmp_path):
        p, fake = parser
        vid = tmp_path / "clip.mp4"
        vid.write_bytes(b"mp4-bytes")
        out = p.extract_video(vid)
        assert out == "# Extracted\n\nmarkdown"
        b64 = base64.b64encode(b"mp4-bytes").decode()
        content = fake.calls[0]["messages"][0]["content"]
        assert content[0] == {"type": "video_url", "video_url": {"url": f"data:video/mp4;base64,{b64}"}}
        assert content[1]["text"].startswith("Produce a complete markdown record")

    def test_extract_video_mov_mime(self, parser, tmp_path):
        p, fake = parser
        vid = tmp_path / "clip.mov"
        vid.write_bytes(b"mov-bytes")
        p.extract_video(vid)
        url = fake.calls[0]["messages"][0]["content"][0]["video_url"]["url"]
        assert url.startswith("data:video/quicktime;base64,")

    def test_extract_video_cache_hit_skips_api(self, parser, tmp_path):
        p, fake = parser
        vid = tmp_path / "clip.mp4"
        vid.write_bytes(b"mp4-bytes")
        p.extract_video(vid)
        p.extract_video(vid)
        assert len(fake.calls) == 1

    def test_video_payload_rejection_includes_hint(self, parser, tmp_path):
        p, fake = parser
        fake._outcomes = [_bad_request_error("base64 video not supported")]
        vid = tmp_path / "clip.mp4"
        vid.write_bytes(b"mp4-bytes")
        with pytest.raises(GLMParserError) as exc:
            p.extract_video(vid)
        assert "public" in str(exc.value)
        assert len(fake.calls) == 1  # a 400 is deterministic — no retries

    def test_video_guard_does_not_read_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(glm_parser_module, "settings", _fake_settings(GLM_VIDEO_MAX_UPLOAD_MB=1))
        parser = GLMParser(cache=OcrCache(tmp_path / "ocr"))
        client, fake = _client_with(["never called"])
        parser._client = client
        reads = []
        monkeypatch.setattr(Path, "read_bytes", lambda self: reads.append(self) or b"")
        big = tmp_path / "huge.mp4"
        big.write_bytes(b"\0" * (2 * 1024 * 1024))
        with pytest.raises(GLMParserError, match="GLM_VIDEO_MAX_UPLOAD_MB"):
            parser.extract_video(big)
        assert reads == []  # guard decides from st_size, never loads the file
