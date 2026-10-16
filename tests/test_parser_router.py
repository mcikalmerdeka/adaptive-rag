"""Tests for src.core.parser_router — parse_mode dispatch with stubbed parsers."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

import src.core.parser_router as router_module
from src.core.file_detector import FileTypeDetector
from src.core.glm_parser import GLMParserError
from src.core.parser_router import ParserRouter

STUB_PDF_MD = "<!-- page 1 -->\n\npdf-md"


class _StubMarkItDown:
    def __init__(self):
        self.calls = []

    def parse(self, path):
        self.calls.append(path)
        return "md-md"


class _StubGLM:
    model_name = "glm-stub"

    def __init__(self):
        self.image_calls, self.pdf_calls, self.video_calls = [], [], []

    def extract_image(self, path):
        self.image_calls.append(path)
        return "img-md"

    def extract_pdf_pages(self, path, progress=None):
        self.pdf_calls.append(path)
        return STUB_PDF_MD

    def extract_video(self, path):
        self.video_calls.append(path)
        return "video-md"


def _router(monkeypatch, scanned=False):
    glm, md = _StubGLM(), _StubMarkItDown()
    monkeypatch.setattr(router_module, "is_scanned_pdf", lambda path: scanned)
    return ParserRouter(markitdown=md, glm=glm), glm, md


def _info(name: str, tmp_path: Path):
    path = tmp_path / name
    path.write_bytes(b"x")  # the router only reads extensions from disk
    return FileTypeDetector().detect(path), path


def _exported_pdf(monkeypatch, tmp_path: Path) -> Path:
    exported = tmp_path / "exported.pdf"
    monkeypatch.setattr(
        router_module.office_renderer, "to_pdf", lambda src, *a, **k: exported
    )
    return exported


# ---- dispatch matrix ---------------------------------------------------------


class TestDocuments:
    def test_md_and_txt_passthrough_all_modes(self, tmp_path, monkeypatch):
        router, glm, md = _router(monkeypatch)
        for ext in (".md", ".txt"):
            for mode in ("auto", "plain", "rendered"):
                info, path = _info(f"f{ext}", tmp_path)
                result = router.parse(info, parse_mode=mode)
                assert result.parser == "passthrough"
                assert result.markdown == "x"
        assert not md.calls and not glm.pdf_calls

    @pytest.mark.parametrize("ext", [".csv", ".html"])
    @pytest.mark.parametrize("mode", ["auto", "plain"])
    def test_csv_html_markitdown(self, tmp_path, monkeypatch, ext, mode):
        router, glm, md = _router(monkeypatch)
        info, path = _info(f"f{ext}", tmp_path)
        result = router.parse(info, parse_mode=mode)
        assert md.calls == [path]
        assert result.parser == "markitdown" and result.markdown == "md-md"
        assert result.pages is None

    @pytest.mark.parametrize("ext", [".csv", ".html"])
    def test_csv_html_rendered_degrades_to_markitdown(
        self, tmp_path, monkeypatch, caplog, ext
    ):
        router, glm, md = _router(monkeypatch)
        info, path = _info(f"f{ext}", tmp_path)
        with caplog.at_level(logging.INFO, logger="src.core.parser_router"):
            result = router.parse(info, parse_mode="rendered")
        assert md.calls == [path]
        assert result.parser == "markitdown"
        assert any(
            "falling back" in r.message and "rendered" in r.message
            for r in caplog.records
        )

    @pytest.mark.parametrize("ext", [".docx", ".pptx", ".xlsx"])
    @pytest.mark.parametrize("mode", ["auto", "plain"])
    def test_office_markitdown(self, tmp_path, monkeypatch, ext, mode):
        router, glm, md = _router(monkeypatch)
        info, path = _info(f"f{ext}", tmp_path)
        result = router.parse(info, parse_mode=mode)
        assert md.calls == [path]
        assert result.parser == "markitdown" and result.pages is None

    @pytest.mark.parametrize("ext", [".docx", ".pptx", ".xlsx"])
    def test_office_rendered_exports_and_ocrs_pages(
        self, tmp_path, monkeypatch, ext
    ):
        router, glm, md = _router(monkeypatch)
        exported = _exported_pdf(monkeypatch, tmp_path)
        info, path = _info(f"f{ext}", tmp_path)
        result = router.parse(info, parse_mode="rendered", progress=lambda c, t: None)
        assert glm.pdf_calls == [exported] and not md.calls
        assert result.parser == "glm-stub"
        assert result.pages == 1

    def test_born_digital_pdf_markitdown(self, tmp_path, monkeypatch):
        router, glm, md = _router(monkeypatch, scanned=False)
        for mode in ("auto", "plain"):
            info, path = _info("doc.pdf", tmp_path)
            result = router.parse(info, parse_mode=mode)
            assert result.markdown == "md-md" and result.parser == "markitdown"
        assert not glm.pdf_calls

    def test_born_digital_pdf_rendered_uses_glm_pages(self, tmp_path, monkeypatch):
        router, glm, md = _router(monkeypatch, scanned=False)
        info, path = _info("doc.pdf", tmp_path)
        result = router.parse(info, parse_mode="rendered")
        assert glm.pdf_calls == [path] and not md.calls
        assert result.parser == "glm-stub" and result.pages == 1

    def test_scanned_pdf_auto_uses_glm_pages(self, tmp_path, monkeypatch):
        router, glm, md = _router(monkeypatch, scanned=True)
        info, path = _info("scan.pdf", tmp_path)
        result = router.parse(info, parse_mode="auto")
        assert glm.pdf_calls == [path]
        assert result.parser == "glm-stub" and result.pages == 1

    def test_scanned_pdf_rendered_uses_glm_pages(self, tmp_path, monkeypatch):
        router, glm, md = _router(monkeypatch, scanned=True)
        info, path = _info("scan.pdf", tmp_path)
        result = router.parse(info, parse_mode="rendered")
        assert glm.pdf_calls == [path] and result.pages == 1

    def test_scanned_pdf_plain_routes_to_markitdown(
        self, tmp_path, monkeypatch, caplog
    ):
        router, glm, md = _router(monkeypatch, scanned=True)
        info, path = _info("scan.pdf", tmp_path)
        with caplog.at_level(logging.WARNING, logger="src.core.parser_router"):
            result = router.parse(info, parse_mode="plain")
        assert md.calls == [path] and not glm.pdf_calls
        assert result.parser == "markitdown"
        assert any("scanned" in r.message.lower() for r in caplog.records)


class TestVisionAlways:
    def test_image_uses_glm_in_every_mode(self, tmp_path, monkeypatch):
        router, glm, md = _router(monkeypatch)
        for mode in ("auto", "plain", "rendered"):
            info, path = _info("shot.png", tmp_path)
            result = router.parse(info, parse_mode=mode)
            assert result.markdown == "img-md" and result.parser == "glm-stub"
        assert glm.image_calls

    def test_video_uses_glm_in_every_mode(self, tmp_path, monkeypatch):
        router, glm, md = _router(monkeypatch)
        for mode in ("auto", "plain", "rendered"):
            info, path = _info("clip.mp4", tmp_path)
            result = router.parse(info, parse_mode=mode)
            assert result.markdown == "video-md" and result.parser == "glm-stub"
            assert result.pages is None
        assert len(glm.video_calls) == 3


# ---- failure paths ------------------------------------------------------------


class TestUnconfigured:
    def test_auto_scanned_falls_back_to_plain(
        self, tmp_path, monkeypatch, caplog
    ):
        router, md = _unconfigured_router(monkeypatch)
        info, path = _info("scan.pdf", tmp_path)
        monkeypatch.setattr(router_module, "is_scanned_pdf", lambda p: True)
        with caplog.at_level(logging.WARNING, logger="src.core.parser_router"):
            result = router.parse(info, parse_mode="auto")
        assert md.calls == [path]
        assert result.parser == "markitdown"
        assert any("unavailable" in r.message for r in caplog.records)

    def test_rendered_scanned_raises(self, tmp_path, monkeypatch):
        router, md = _unconfigured_router(monkeypatch)
        info, path = _info("scan.pdf", tmp_path)
        monkeypatch.setattr(router_module, "is_scanned_pdf", lambda p: True)
        with pytest.raises(GLMParserError):
            router.parse(info, parse_mode="rendered")
        assert not md.calls

    def test_video_unconfigured_raises_valueerror(self, tmp_path, monkeypatch):
        router, md = _unconfigured_router(monkeypatch)
        info, path = _info("clip.mp4", tmp_path)
        with pytest.raises(ValueError, match="ZAI_API_KEY"):
            router.parse(info, parse_mode="auto")

    def test_bad_parse_mode_raises_valueerror(self, tmp_path, monkeypatch):
        router, glm, md = _router(monkeypatch)
        info, path = _info("f.csv", tmp_path)
        with pytest.raises(ValueError, match="parse_mode"):
            router.parse(info, parse_mode="turbo")


def _unconfigured_router(monkeypatch):
    """Router whose GLM lazy-init raises (ZAI_API_KEY missing in .env)."""
    md = _StubMarkItDown()
    router = ParserRouter(markitdown=md, glm=None)

    def _broken():
        raise GLMParserError("ZAI_API_KEY is not set.")

    monkeypatch.setattr(router, "_get_glm", _broken)
    return router, md
