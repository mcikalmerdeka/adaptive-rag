"""Tests for src.core.parser_router — dispatch table with stubbed parsers."""

from __future__ import annotations

from pathlib import Path

import pytest

import src.core.parser_router as router_module
from src.core.file_detector import FileTypeDetector
from src.core.glm_parser import GLMParserError
from src.core.parser_router import ParserRouter


class _StubGLM:
    model_name = "glm-stub"

    def __init__(self):
        self.image_calls, self.pdf_calls, self.video_calls = [], [], []

    def extract_image(self, path):
        self.image_calls.append(path)
        return "img-md"

    def extract_pdf_pages(self, path, progress=None):
        self.pdf_calls.append(path)
        return "<!-- page 1 -->\n\npdf-md"

    def extract_video(self, path):
        self.video_calls.append(path)
        return "video-md"


class _StubDocling:
    def __init__(self):
        self.calls = []

    def parse(self, path):
        self.calls.append(path)
        return "docling-md"


def _router(monkeypatch, scanned=False):
    glm, docling = _StubGLM(), _StubDocling()
    monkeypatch.setattr(router_module, "is_scanned_pdf", lambda path: scanned)
    return ParserRouter(docling=docling, glm=glm), glm, docling


def _info(name: str, tmp_path: Path):
    path = tmp_path / name
    path.write_bytes(b"x")  # extension is all the router reads from disk
    return FileTypeDetector().detect(path), path


class TestDispatch:
    def test_video_routes_to_glm_video(self, tmp_path, monkeypatch):
        router, glm, docling = _router(monkeypatch)
        info, path = _info("clip.mp4", tmp_path)
        result = router.parse(info)
        assert result.markdown == "video-md"
        assert result.parser == "glm-stub"
        assert result.pages is None
        assert glm.video_calls == [path] and not docling.calls

    def test_image_routes_to_glm_image(self, tmp_path, monkeypatch):
        router, glm, docling = _router(monkeypatch)
        info, path = _info("shot.png", tmp_path)
        result = router.parse(info)
        assert result.markdown == "img-md" and result.parser == "glm-stub"
        assert glm.image_calls == [path]

    def test_force_vlm_for_pdf_overrides_born_digital(self, tmp_path, monkeypatch):
        router, glm, docling = _router(monkeypatch, scanned=False)
        info, path = _info("doc.pdf", tmp_path)
        router.parse(info, force_vlm_for_pdf=True)
        assert glm.pdf_calls == [path] and not docling.calls

    def test_scanned_pdf_heuristic_routes_to_glm(self, tmp_path, monkeypatch):
        router, glm, docling = _router(monkeypatch, scanned=True)
        info, path = _info("scan.pdf", tmp_path)
        router.parse(info)
        assert glm.pdf_calls == [path]

    def test_born_digital_pdf_routes_to_docling(self, tmp_path, monkeypatch):
        router, glm, docling = _router(monkeypatch, scanned=False)
        info, path = _info("doc.pdf", tmp_path)
        result = router.parse(info)
        assert result.markdown == "docling-md" and result.parser == "docling"

    def test_docx_routes_to_docling(self, tmp_path, monkeypatch):
        router, glm, docling = _router(monkeypatch)
        info, path = _info("doc.docx", tmp_path)
        router.parse(info)
        assert docling.calls == [path]


class TestUnconfigured:
    def test_pdf_falls_back_to_docling_when_glm_unconfigured(self, tmp_path, monkeypatch):
        router = ParserRouter(docling=_StubDocling(), glm=None)

        def _broken():
            raise GLMParserError("ZAI_API_KEY is not set.")

        monkeypatch.setattr(router, "_get_glm", _broken)
        info, _ = _info("scan.pdf", tmp_path)
        monkeypatch.setattr(router_module, "is_scanned_pdf", lambda path: True)
        result = router.parse(info)
        assert result.parser == "docling"

    def test_video_unconfigured_raises_valueerror(self, tmp_path, monkeypatch):
        router = ParserRouter(docling=_StubDocling(), glm=None)

        def _broken():
            raise GLMParserError("ZAI_API_KEY is not set.")

        monkeypatch.setattr(router, "_get_glm", _broken)
        info, _ = _info("clip.mp4", tmp_path)
        with pytest.raises(ValueError, match="ZAI_API_KEY"):
            router.parse(info)
