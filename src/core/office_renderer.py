"""Office-document → PDF layout engine export.

Rendered-mode prerequisite per the spec: a paginated view of DOCX/PPTX/
XLSX can only come from a layout engine — MS Office COM first (per the
notebook: Word ``SaveAs2`` fmt 17, PowerPoint ``SaveAs`` fmt 32, Excel
``ExportAsFixedFormat`` fmt 0), then LibreOffice headless, then a clear
error with manual-export guidance.

Exports are content-keyed: ``<stem>_<sha256[:8]>.pdf``. A byte-identical
export from a previous ingestion is reused untouched, which keeps page
PNGs (and therefore the GLM OCR cache) stable across re-ingests.
"""

from __future__ import annotations

import hashlib
import importlib
import logging
import shutil
import subprocess
from pathlib import Path

from src.config import settings

logger = logging.getLogger(__name__)

CONVERTIBLE_EXTENSIONS = {".docx", ".pptx", ".xlsx"}

SOFFICE_TIMEOUT_SEC = 600

# Reason from the most recent COM export attempt that raised, or None when
# COM was absent/unused. ``to_pdf`` turns this into a distinct, actionable
# error ("Office IS installed, the export failed") instead of telling an
# Office user to install Office.
_com_failure: str | None = None


def _find_soffice() -> str | None:
    """Locate the LibreOffice binary, or None."""
    return shutil.which("soffice") or shutil.which("soffice.exe")


def _com_export(source: Path, dest: Path) -> bool:
    """Export via Office COM. Returns False when COM is unusable.

    pywin32 is imported lazily inside this function so machines without
    it (Linux/containers) never break the import of this module — the
    caller just falls through to LibreOffice.
    """
    # Hold the module object itself: attribute access on the parent package
    # breaks when a pre-existing sys.modules child wasn't setattr'd.
    global _com_failure
    _com_failure = None
    try:
        client = importlib.import_module("win32com.client")
        pythoncom = importlib.import_module("pythoncom")
    except Exception as exc:  # ImportError falls here on non-Windows hosts
        logger.info(f"Office COM unavailable ({type(exc).__name__}): {exc}")
        return False
    dispatch = getattr(client, "Dispatch", None)
    if dispatch is None:
        logger.warning(
            "win32com.client has no Dispatch attribute — pretending COM is "
            "unavailable"
        )
        return False

    # COM is thread-local: join this thread into an STA apartment (worker
    # threads like Gradio's handlers never do this themselves), balance it
    # with CoUninitialize, and tolerate a thread already in another
    # apartment (RPC_E_CHANGED_MODE) where COM is usable as-is.
    try:
        pythoncom.CoInitialize()
        com_initialized = True
    except pythoncom.com_error as exc:
        logger.info(
            f"CoInitialize skipped ({type(exc).__name__}: {exc}); using the "
            f"thread's existing COM apartment"
        )
        com_initialized = False

    resolved_src = source.resolve()
    resolved_dest = dest.resolve()
    app = None
    try:
        if source.suffix.lower() == ".docx":
            app = dispatch("Word.Application")
            doc = app.Documents.Open(str(resolved_src), ReadOnly=True)
            try:
                doc.SaveAs2(str(resolved_dest), 17)  # 17 = wdFormatPDF
            finally:
                doc.Close(False)
        elif source.suffix.lower() == ".pptx":
            app = dispatch("PowerPoint.Application")
            pres = app.Presentations.Open(str(resolved_src), True, False, False)
            try:
                pres.SaveAs(str(resolved_dest), 32)  # 32 = ppSaveAsPDF
            finally:
                pres.Close()
        elif source.suffix.lower() == ".xlsx":
            app = dispatch("Excel.Application")
            app.DisplayAlerts = False
            wb = app.Workbooks.Open(str(resolved_src), 0, True)  # UpdateLinks=0, ReadOnly=True
            try:
                wb.ExportAsFixedFormat(0, str(resolved_dest))  # 0 = xlTypePDF
            finally:
                wb.Close(False)
        else:
            raise ValueError(
                f"COM export supports only {sorted(CONVERTIBLE_EXTENSIONS)}, "
                f"got {source.suffix.lower()}"
            )
        return True
    except Exception as exc:
        _com_failure = f"{type(exc).__name__}: {exc}"
        logger.warning(
            f"Office COM export failed for {source.name}: {_com_failure}"
        )
        return False
    finally:
        if app is not None:
            app.Quit()
        if com_initialized:
            pythoncom.CoUninitialize()


def _soffice_export(
    source: Path,
    out_dir: Path,
    timeout: int = SOFFICE_TIMEOUT_SEC,
) -> bool:
    """Export via LibreOffice headless. Returns False when unavailable/failed."""
    soffice = _find_soffice()
    if not soffice:
        logger.info("LibreOffice not found (soffice not on PATH)")
        return False

    try:
        subprocess.run(
            [
                soffice,
                "--headless",
                "--norestore",
                "--convert-to",
                "pdf",
                "--outdir",
                str(out_dir),
                str(source),
            ],
            check=True,
            capture_output=True,
            timeout=timeout,
        )
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        logger.warning(
            f"LibreOffice export failed for {source.name}: {type(exc).__name__}: {exc}"
        )
        return False


def to_pdf(file_path: str | Path, out_dir: str | Path | None = None) -> Path:
    """Render an office document to its cached PDF twin.

    Returns an existing content-keyed export untouched; otherwise runs the
    auto-detected engine (COM → soffice) and renames soffice's ``<stem>.pdf``
    into the content-keyed name.
    """
    source = Path(file_path).resolve()
    if not source.exists():
        raise FileNotFoundError(f"File not found: {source}")

    ext = source.suffix.lower()
    if ext not in CONVERTIBLE_EXTENSIONS:
        raise ValueError(
            f"Only {sorted(CONVERTIBLE_EXTENSIONS)} have a rendered path; "
            f"cannot render {source.name} (extension {ext})"
        )

    out = Path(out_dir) if out_dir is not None else settings.CACHE_DIR / "office_pdf"
    out.mkdir(parents=True, exist_ok=True)

    content_key = hashlib.sha256(source.read_bytes()).hexdigest()[:8]
    dest = out / f"{source.stem}_{content_key}.pdf"
    if dest.exists():
        logger.info(f"Reusing rendered PDF: {dest.name}")
        return dest

    if _com_export(source, dest):
        return dest

    if _soffice_export(source, out):
        soffice_output = out / f"{source.stem}.pdf"
        if soffice_output.exists():
            soffice_output.replace(dest)
            return dest

    if _com_failure:
        # Office is installed but the export failed (locked file, password,
        # corrupt doc...). Telling this user to "install MS Office" is wrong.
        raise RuntimeError(
            f"Office COM export failed for '{source.name}': {_com_failure}\n"
            "- Option A: close the file in Office / check document passwords "
            "/ repair the file, then retry\n"
            "- Option B: install LibreOffice (soffice on PATH) as the "
            "fallback engine\n"
            "- Option C: export the PDF yourself and use plain mode instead"
        )

    raise RuntimeError(
        f"No layout engine available to render '{source.name}' to PDF.\n"
        "- Option A: install MS Office (Word/PowerPoint/Excel — the COM path "
        "is used automatically)\n"
        "- Option B: install LibreOffice and put soffice on PATH\n"
        "- Option C: export the PDF yourself and use plain mode instead"
    )


def available_engine() -> str:
    """Which layout engine would ``to_pdf`` use today: "com" | "soffice" | "none"."""
    try:
        client = importlib.import_module("win32com.client")
        if not hasattr(client, "Dispatch"):
            raise AttributeError("missing Dispatch")
    except Exception as exc:
        logger.debug(f"pywin32 unavailable: {type(exc).__name__}: {exc}")
    else:
        return "com"
    return "soffice" if _find_soffice() else "none"
