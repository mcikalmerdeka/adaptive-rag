"""Tests for src.core.office_renderer — layout-engine auto-detect + export caching.

Real COM is never touched: pywin32 is simulated via sys.modules injection
(absence simulated with the documented ``None`` entry), soffice via stubbed
module seams (_com_export/_soffice_export/_find_soffice, subprocess.run,
shutil.which).
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
import types
from pathlib import Path

import pytest

import src.core.office_renderer as ore


# ---- helpers ---------------------------------------------------------------


def _hash8(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:8]


def _make_office_file(tmp_path: Path, ext: str, payload: bytes) -> Path:
    p = tmp_path / f"report{ext}"
    p.write_bytes(payload)
    return p


class _Rec:
    """Fake COM object: chainable, callable, and recording.

    Every attribute access returns another ``_Rec`` that records its name
    when *called*, so chains like
    ``app.Documents.Open(...).SaveAs2(...).Close(...)`` all land in ``calls``.
    """

    def __init__(self, calls: list, name: str | None = None):
        self._calls = calls
        self._name = name

    def __call__(self, *args, **kwargs):
        if self._name is not None:
            self._calls.append((self._name, args, kwargs))
        return _Rec(self._calls)

    def Open(self, *args, **kwargs):
        self._calls.append(("Open", args, kwargs))
        return _Rec(self._calls)

    def __getattr__(self, name):
        if name.startswith("_Rec"):
            raise AttributeError(name)
        return _Rec(self._calls, name)


def _fake_com_module(calls: list) -> types.ModuleType:
    """Fake ``win32com.client`` whose Dispatch returns recording proxies."""

    mod = types.ModuleType("win32com.client")
    mod.Dispatch = lambda prog_id, _c=calls: (
        _c.append(("Dispatch", (prog_id,), {})),
        _Rec(_c),
    )[1]
    return mod


# ---- export caching & naming -----------------------------------------------


def test_dest_is_content_hashed(tmp_path, monkeypatch):
    """Same stem in different directories: the hash key decides the name."""
    dir_a = tmp_path / "src_a"
    dir_b = tmp_path / "src_b"
    dir_a.mkdir()
    dir_b.mkdir()
    monkeypatch.setattr(ore, "_com_export", lambda s, d: True)

    pdf_a = ore.to_pdf(_make_office_file(dir_a, ".docx", b"content-A"), tmp_path / "out1")
    pdf_b = ore.to_pdf(_make_office_file(dir_b, ".docx", b"content-B"), tmp_path / "out2")

    assert pdf_a.name == f"report_{_hash8(b'content-A')}.pdf"
    assert pdf_b.name == f"report_{_hash8(b'content-B')}.pdf"
    assert pdf_a.name != pdf_b.name


def test_skip_if_exists_reuses_export(tmp_path, monkeypatch):
    payload = b"original-doc-bytes"
    src = _make_office_file(tmp_path, ".pptx", payload)
    monkeypatch.setattr(ore, "_com_export", lambda s, d: True)
    dest = ore.to_pdf(src, tmp_path)
    dest.write_bytes(b"PREVIOUS-EXPORT")

    def _forbidden(*a, **k):
        raise AssertionError("layout engines must not run when dest exists")

    monkeypatch.setattr(ore, "_com_export", _forbidden)
    monkeypatch.setattr(ore, "_soffice_export", _forbidden)

    dest2 = ore.to_pdf(src, tmp_path)
    assert dest2 == dest
    assert dest2.read_bytes() == b"PREVIOUS-EXPORT"


# ---- engine precedence ------------------------------------------------------


def test_com_export_takes_precedence(tmp_path, monkeypatch):
    src = _make_office_file(tmp_path, ".docx", b"x")
    monkeypatch.setattr(ore, "_com_export", lambda s, d: True)
    soffice_calls = []
    monkeypatch.setattr(ore, "_soffice_export", lambda *a, **k: soffice_calls.append(1))

    dest = ore.to_pdf(src, tmp_path)
    assert dest.name == f"report_{_hash8(b'x')}.pdf"
    assert not soffice_calls


def test_com_unavailable_falls_to_soffice(tmp_path, monkeypatch):
    src = _make_office_file(tmp_path, ".xlsx", b"workbook")
    out_dir = tmp_path / "out"
    monkeypatch.setattr(ore, "_com_export", lambda s, d: False)

    def _fake_soffice_export(source: Path, out: Path, timeout: int = 600) -> bool:
        (out / f"{source.stem}.pdf").write_bytes(b"pdf")
        return True

    monkeypatch.setattr(ore, "_soffice_export", _fake_soffice_export)
    dest = ore.to_pdf(src, out_dir)
    assert dest.name == f"report_{_hash8(b'workbook')}.pdf"
    assert dest.read_bytes() == b"pdf"


def test_com_unavailable_falls_to_soffice_realpath(tmp_path, monkeypatch):
    """pywin32 absent (Linux): ``import win32com.client`` raises from the
    documented None sys.modules entry; the real _com_export returns False."""
    src = _make_office_file(tmp_path, ".docx", b"z")
    out_dir = tmp_path / "out"
    monkeypatch.setitem(sys.modules, "win32com.client", None)

    def _fake_soffice_export(source: Path, out: Path, timeout: int = 600) -> bool:
        (out / f"{source.stem}.pdf").write_bytes(b"pdf-from-soffice")
        return True

    monkeypatch.setattr(ore, "_soffice_export", _fake_soffice_export)
    dest = ore.to_pdf(src, out_dir)
    assert dest.read_bytes() == b"pdf-from-soffice"


def test_no_engine_raises_with_options(tmp_path, monkeypatch):
    src = _make_office_file(tmp_path, ".docx", b"z")
    monkeypatch.setattr(ore, "_com_export", lambda s, d: False)
    monkeypatch.setattr(ore, "_soffice_export", lambda s, o, timeout=600: False)

    with pytest.raises(RuntimeError) as excinfo:
        ore.to_pdf(src, tmp_path)
    message = str(excinfo.value)
    assert "No layout engine" in message
    assert "Office" in message
    assert "LibreOffice" in message
    assert "Option B" in message


def test_com_present_but_export_failed_raises_com_guidance(tmp_path, monkeypatch):
    """Office IS installed (win32com importable) but the export raised (e.g.
    the file is open in Word / password-protected). The user must not be
    told to "install MS Office"."""
    src = _make_office_file(tmp_path, ".docx", b"locked-doc")
    out_dir = tmp_path / "out"

    class _Docs:
        def Open(self, *args, **kwargs):
            raise RuntimeError("file is locked by another process")

    class _WordApp:
        Documents = _Docs()

        def Quit(self):
            pass

    fake = types.ModuleType("win32com.client")
    fake.Dispatch = lambda prog_id: _WordApp()
    monkeypatch.setitem(sys.modules, "win32com.client", fake)
    monkeypatch.setattr(ore, "_soffice_export", lambda s, o, timeout=600: False)

    with pytest.raises(RuntimeError) as excinfo:
        ore.to_pdf(src, out_dir)
    message = str(excinfo.value)
    assert "Office COM export failed" in message
    assert "locked by another process" in message
    assert "No layout engine" not in message


# ---- soffice invocation details ---------------------------------------------


def test_soffice_export_argv_and_timeout(tmp_path, monkeypatch):
    src = _make_office_file(tmp_path, ".docx", b"a")
    argv_list = []
    kwargs = {}

    def _fake_run(argv, **kw):
        argv_list.append(list(argv))
        kwargs.update(kw)
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(ore.shutil, "which", lambda name: "soffice")
    monkeypatch.setattr(ore.subprocess, "run", _fake_run)
    assert ore._soffice_export(src, tmp_path) is True

    argv = argv_list[0]
    assert argv[0] == "soffice"
    assert "--headless" in argv and "--norestore" in argv
    assert argv[argv.index("--convert-to") + 1] == "pdf"
    assert Path(argv[argv.index("--outdir") + 1]) == tmp_path
    assert argv[-1] == str(src)
    assert kwargs.get("timeout") == 600
    assert kwargs.get("check") is True
    assert kwargs.get("capture_output") is True


def test_soffice_export_unavailable_returns_false(tmp_path, monkeypatch):
    src = _make_office_file(tmp_path, ".docx", b"a")
    monkeypatch.setattr(ore.shutil, "which", lambda name: None)
    assert ore._soffice_export(src, tmp_path) is False


# ---- extension gate ----------------------------------------------------------

_CONVERTIBLE = {".docx", ".pptx", ".xlsx"}


@pytest.mark.parametrize("ext", [".md", ".csv", ".pdf", ".html", ".txt"])
def test_unsupported_extension_raises(tmp_path, ext):
    assert ext not in _CONVERTIBLE
    src = tmp_path / f"doc{ext}"
    src.write_bytes(b"x")
    with pytest.raises(ValueError, match=ext):
        ore.to_pdf(src, tmp_path)


# ---- real COM path with fake win32com ----------------------------------------


@pytest.mark.parametrize(
    ("ext", "expected_fmt"),
    [(".docx", 17), (".pptx", 32), (".xlsx", 0)],
)
def test_format_codes_per_app(tmp_path, monkeypatch, ext, expected_fmt):
    src = _make_office_file(tmp_path, ext, f"payload{ext}".encode())
    calls: list = []
    monkeypatch.setitem(sys.modules, "win32com.client", _fake_com_module(calls))

    ok = ore._com_export(src, tmp_path / "out.pdf")
    assert ok is True

    saves = [c for c in calls if c[0] in {"SaveAs2", "SaveAs", "ExportAsFixedFormat"}]
    assert len(saves) == 1
    name, args, _kw = saves[0]
    # SaveAs2/SaveAs receive (dest, fmt); ExportAsFixedFormat receives (fmt, dest).
    fmt = args[1] if name in {"SaveAs2", "SaveAs"} else args[0]
    assert fmt == expected_fmt

    opens = [c for c in calls if c[0] == "Open"]
    if ext == ".docx":
        assert opens and opens[0][2].get("ReadOnly") is True
    elif ext == ".pptx":
        assert opens and opens[0][1] == (str(src.resolve()), True, False, False)
    elif ext == ".xlsx":
        assert opens and opens[0][1] == (str(src.resolve()), 0, True)


# ---- COM apartment lifecycle -------------------------------------------------


def test_com_export_initializes_and_uninitializes_com(tmp_path, monkeypatch):
    """Gradio runs handlers on worker threads that never initialized COM —
    _com_export must CoInitialize (and CoUninitialize) around the export."""
    src = _make_office_file(tmp_path, ".docx", b"payload")
    calls: list = []
    monkeypatch.setitem(sys.modules, "win32com.client", _fake_com_module(calls))

    fake_pythoncom = types.ModuleType("pythoncom")

    class _ComError(Exception):
        pass

    fake_pythoncom.com_error = _ComError
    fake_pythoncom.CoInitialize = lambda: calls.append(("CoInitialize", (), {}))
    fake_pythoncom.CoUninitialize = lambda: calls.append(
        ("CoUninitialize", (), {})
    )
    monkeypatch.setitem(sys.modules, "pythoncom", fake_pythoncom)

    ok = ore._com_export(src, tmp_path / "out.pdf")
    assert ok is True

    order = [c[0] for c in calls]
    assert "CoInitialize" in order and "CoUninitialize" in order
    assert order.index("CoInitialize") < order.index("Dispatch")
    assert order.index("CoUninitialize") > order.index("Quit")
    assert order.count("CoInitialize") == 1
    assert order.count("CoUninitialize") == 1


def test_com_export_skips_uninitialize_when_apartment_conflict(
    tmp_path, monkeypatch
):
    """A thread already in a different COM apartment raises com_error
    (RPC_E_CHANGED_MODE) on CoInitialize; COM is then usable as-is and must
    NOT be uninitialized by us (we never successfully Initialize'd it)."""
    src = _make_office_file(tmp_path, ".pptx", b"deck")
    calls: list = []
    monkeypatch.setitem(sys.modules, "win32com.client", _fake_com_module(calls))

    fake_pythoncom = types.ModuleType("pythoncom")

    class _ComError(Exception):
        pass

    def _init_raises():
        calls.append(("CoInitializeErr", (), {}))
        raise _ComError(-2147221015, "RPC_E_CHANGED_MODE", None, None)

    fake_pythoncom.com_error = _ComError
    fake_pythoncom.CoInitialize = _init_raises
    fake_pythoncom.CoUninitialize = lambda: calls.append(
        ("CoUninitialize", (), {})
    )
    monkeypatch.setitem(sys.modules, "pythoncom", fake_pythoncom)

    ok = ore._com_export(src, tmp_path / "out.pdf")
    assert ok is True

    order = [c[0] for c in calls]
    assert "CoInitializeErr" in order
    assert "CoUninitialize" not in order


# ---- capability reporting -----------------------------------------------------


def test_available_engine_reports_com_when_win32_present(monkeypatch):
    monkeypatch.setitem(sys.modules, "win32com.client", _fake_com_module([]))
    monkeypatch.setattr(ore, "_find_soffice", lambda: None)
    assert ore.available_engine() == "com"


def test_available_engine_reports_soffice_without_win32(monkeypatch):
    monkeypatch.setitem(sys.modules, "win32com.client", None)
    monkeypatch.setattr(ore, "_find_soffice", lambda: "soffice.exe")
    assert ore.available_engine() == "soffice"


def test_available_engine_none_without_engine(monkeypatch):
    monkeypatch.setitem(sys.modules, "win32com.client", None)
    monkeypatch.setattr(ore, "_find_soffice", lambda: None)
    assert ore.available_engine() == "none"
