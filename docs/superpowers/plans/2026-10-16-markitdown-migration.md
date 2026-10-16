# Docling → MarkItDown Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Docling with Microsoft's MarkItDown for digital document parsing, and give every paginated format a second "render to images → GLM OCR" processing path selectable via `parse_mode` (`auto` | `plain` | `rendered`).

**Architecture:** Single `ParserRouter` keeps its dispatch role; `force_vlm_for_pdf` becomes `parse_mode`. Two new modules: `MarkItDownParser` (thin wrapper, like DoclingParser was) and `office_renderer` (office→PDF layout engine, notebook-verified COM→soffice precedence, content-hash skip-if-exists export caching). Rendered glue reuses `GLMParser.extract_pdf_pages` + `pypdfium2` rendering unchanged.

**Tech Stack:** Python 3.14 / uv venv; `markitdown[all]` 0.1.8 (installed); `pywin32` (Windows marker); existing `pypdfium2`, `openai`, `tenacity`, Gradio.

**Spec:** `docs/superpowers/specs/2026-10-16-markitdown-migration-design.md` — the plan argues from the spec; executors read both.

## Global Constraints

- Working venv: `.venv` (Python 3.14.3, markitdown 0.1.8 confirmed). Run tests as `.venv\Scripts\python.exe -m pytest tests/<file> -v` (PowerShell).
- New deps: add `pywin32; sys_platform == 'win32'` **exactly** (marker included) to `pyproject.toml` and `requirements.txt`. Remove `langchain-docling` from both. No PyMuPDF. No other new deps.
- No MarkItDown LLM features anywhere (`llm_client`/`llm_model` kwargs unused).
- Provenance strings: `"markitdown"`, `"passthrough"`, or the resolved GLM model code (e.g. `"glm-5.3-flash"`). No `"docling"` string remains in `src/`, `tests/`, `scripts/`, `app.py`, `Dockerfile`, `pyproject.toml`, `requirements.txt` after Task 8.
- `parse_mode` values exactly `"auto" | "plain" | "rendered"`; bad value → `ValueError` naming the three options.
- Touching auth/secrets/encryption is forbidden; settings edits are limited to none (no `settings.py` changes needed).
- Commit style: conventional prefixes (`feat:`, `refactor:`, `docs:`, `chore:`), imperative. Push allowed on branch `feat/docling-to-markitdown-migration`; **never merge**.
- No browser automation / Playwright / agent-browser at any task. UI verification is the owner's manual pass.
- The suite is expected RED at Task 1 (fresh venv lacks docling; `src/core/__init__.py` still imports it). Every task must leave the tests it owns green; the whole suite is green from Task 5 onward.

## Review Focus

Failure modes the spec implies that no single task's tests fully exercise; each is pinned by the named test in the owning task:

1. **pywin32 absent (Linux/Docker) never breaks imports or the plain path** — module-level lazy COM import; `available_engine()` honestly reports `"none"` → expect plain conversions to still work and rendered mode to error with clear guidance, not an ImportError traceback. Pinned: `test_com_unavailable_falls_to_soffice` + `test_available_engine_none_without_win32` (Task 3).
2. **Re-ingesting an unchanged office file must hit caches, not re-pay** — deterministic `<stem>_<hash8>.pdf` name + skip-if-exists → byte-identical page PNGs → GLM OCR cache hits. Pinned: `test_dest_is_content_hashed`, `test_skip_if_exists_reuses_export` (Task 3).
3. **Scanned PDF in plain mode is honored (weak output + warning), not silently garbage** — user chose the cheap path; expect `parser == "markitdown"` output from the text layer plus a logged warning, no GLM call. Pinned: `test_scanned_pdf_plain_routes_to_markitdown` (Task 4).
4. **Office COM export must use each app's correct PDF format code** (Word 17 / PowerPoint 32 / Excel 0) or exports silently glorify the wrong format. Pinned: `test_format_codes_per_app` (Task 3).
5. **No layout engine available** must produce the notebook's Option A/B/C guidance error, not a bare soffice CalledProcessError. Pinned: `test_no_engine_raises_with_options` (Task 3), surfaced through `test_rendered_without_glm_raises` (Task 4, GLM side).

---

### Task 1: Dependency hygiene

**Files:**
- Modify: `pyproject.toml` (dependencies array)
- Modify: `requirements.txt`
- Re-lock via uv

**Interfaces:**
- Consumes: nothing
- Produces: installed `pywin32` in `.venv`; `langchain-docling` gone; clean lockfiles everything later imports against

- [x] **Step 1: Edit `pyproject.toml`** — remove the `"langchain-docling>=3.0.0",` line; add `"pywin32; sys_platform == 'win32'",`. Alphabetical position (after `psycopg[binary]`).
- [x] **Step 2: Edit `requirements.txt`** — remove `langchain-docling`; add `pywin32; sys_platform == 'win32'` after `psycopg[binary]`.
- [x] **Step 3: Re-lock and install** — run `uv lock` then `uv sync`. Expected: exits 0; `pywin32` appears in the resolution for Windows.
- [x] **Step 4: Verify imports**
  ```powershell
  .venv\Scripts\python.exe -c "import pywin32; import win32com.client; import markitdown, pypdfium2; print('ok')"
  ```
  Expected: `ok`
- [x] **Step 5: Commit** `chore: swap langchain-docling for pywin32 (win32-only marker) and re-lock`

---

### Task 2: `MarkItDownParser` module (TDD)

**Files:**
- Create: `src/core/markitdown_parser.py`
- Test: `tests/test_markitdown_parser.py`

**Interfaces:**
- Consumes: `markitdown.MarkItDown`, exceptions `FileConversionException` / `MissingDependencyException`, result type `DocumentConverterResult` (all importable from `markitdown` top-level — verified in `.venv`).
- Produces: `MarkItDownParserError(Exception)` and `MarkItDownParser.parse(self, file_path: str | Path) -> str` (used by Task 4's router and Task 5's converter).

- [x] **Step 1: Write the failing tests in `tests/test_markitdown_parser.py`**
  - `test_csv_converts_offline` — write `name,qty\nwidget,3\n` to a tmp `.csv`; `md = MarkItDownParser().parse(p)`; assert `"widget" in md` and `"|" in md`, and `isinstance(md, str)`.
  - `test_missing_file_raises_filenotfound` — nonexistent path → `pytest.raises(FileNotFoundError)`.
  - `test_conversion_exception_wrapped` — monkeypatch the parser's `_converter.convert` to raise `FileConversionException("boom")`; `pytest.raises(MarkItDownParserError, match="boom")`.
  - `test_missing_dependency_wrapped` — same, raising `MissingDependencyException("gone")`; expect `MarkItDownParserError, match="gone"`.
  - `test_empty_output_returns_empty_string_and_logs` — monkeypatch `convert` to return `DocumentConverterResult(markdown="")`; result `== ""`; `caplog` contains a warning.
- [x] **Step 2: Run tests to verify they fail**
  `​.venv\Scripts\python.exe -m pytest tests/test_markitdown_parser.py -v` → FAIL (module does not exist).
- [x] **Step 3: Implement `src/core/markitdown_parser.py`** *(executed per Task 2 ledger ruling: additionally folded the import-chain decoupling — core/__init__.py exports, converter error import/tuple, interim router rewiring, docling_parser.py deletion, preloader docling-block removal — into this task's commit)*
  - Module docstring: one instance, no LLM kwargs, no `warm_up()` (model-free) — follows the wrapper pattern of the deleted DoclingParser.
  - `__init__` stores `self._converter = MarkItDown(enable_plugins=False)` and logs init.
  - `parse`: existence check first (raise `FileNotFoundError`); wrap the `convert()` call — catch `(FileConversionException, MissingDependencyException, Exception)` → raise `MarkItDownParserError(f"MarkItDown failed on {path.name}: {exc}")`; empty markdown → `logger.warning(...)` + `return ""`; else INFO log chars and return.
- [x] **Step 4: Run tests to verify they pass** (all 5 PASS)
- [x] **Step 5: Commit** `feat: add MarkItDownParser wrapper for plain document conversion`

---

### Task 3: `office_renderer` module (TDD)

**Files:**
- Create: `src/core/office_renderer.py`
- Test: `tests/test_office_renderer.py`

**Interfaces:**
- Consumes: `pywin32` COM (lazy import), `subprocess`, `shutil.which`, `settings.CACHE_DIR` from `src.config`.
- Produces (Task 4 depends on exactly these):
  ```python
  def to_pdf(file_path: str | Path, out_dir: str | Path | None = None) -> Path
  def available_engine() -> str          # "com" | "soffice" | "none"
  ```
  Test seams (module-level, monkeypatchable): `_com_export(source: Path, dest: Path) -> bool`, `_soffice_export(source: Path, out_dir: Path, timeout: int = 600) -> bool`, `_find_soffice() -> str | None`.
- Rendered-capable extensions: `{".docx", ".pptx", ".xlsx"}`; anything else → `ValueError`.

- [x] **Step 1: Write the failing tests in `tests/test_office_renderer.py`** *(implemented as listed; the fake COM recorder is a chainable `Dispatch`-capable proxy)*
  - `test_dest_is_content_hashed` — two files with the same stem but different bytes in one `out_dir=None`-run (`out_dir` given as tmp): returned names differ and equal `f"{stem}_{sha256[:8]}.pdf"` (compute expected hash in the test).
  - `test_skip_if_exists_reuses_export` — pre-create the expected dest file with marker bytes; monkeypatch `_com_export` to fail-fast (raise if called); `to_pdf` returns that path with marker bytes intact.
  - `test_com_export_takes_precedence` — `_com_export` stub returns True (writes dest): returns dest; `_soffice_export` **not** called.
  - `test_com_unavailable_falls_to_soffice` — `_com_export` returns False; `_soffice_export` stub True → dest returned (soffice output `<stem>.pdf` gets renamed by the module to the content-hashed name).
  - `test_no_engine_raises_with_options` — both stubs False → `pytest.raises(RuntimeError, match="No layout engine")`; message contains "MS Word" or "Office", "LibreOffice", and "SoChoose"/Option guidance (assert `'Option B'` in str or similar via spec wording).
  - `test_soffice_export_flags` — stub `shutil.which` to return `"soffice"`; monkeypatch `subprocess.run` capturing argv; assert `--headless`, `--norestore`, `--convert-to`, `pdf`, `--outdir`, and `timeout=600` present.
  - `test_unsupported_extension_raises` — `to_pdf` on a `.md`/`.csv` file → `ValueError` naming the extension and the supported three.
  - `test_format_codes_per_app` — monkeypatch `sys.modules["win32com.client"]` with a fake module whose `Dispatch` returns a recorder per ProgID: `"Word.Application"` → object whose `Documents.Open(...)` yields a doc recording `SaveAs2(dest, fmt)`; same idea for PowerPoint (`Presentations.Open` → `SaveAs(dest, fmt)`), Excel (`Workbooks.Open(path, UpdateLinks=0, ReadOnly=True)` → `ExportAsFixedFormat(fmt, dest)`). Parametrize ext→expected: docx→17, pptx→32, xlsx→0; also assert Word popen called with `ReadOnly=True`.
  - `test_com_unavailable_falls_to_soffice_realpath` — `monkeypatch.setitem(sys.modules, "win32com.client", None)` (simulates Linux without pywin32: `import` raises from None entry) + `_soffice_export` stub True → still succeeds.
  - `test_available_engine_*` — with fake win32com present → `"com"`; with win32 hidden (`None` entry) and `_find_soffice`→`"soffice.exe"` → `"soffice"`; both absent → `"none"`.
- [x] **Step 2: Run tests to verify they fail** (module missing)
- [x] **Step 3: Implement `src/core/office_renderer.py`** *(per Task 3 ledger ruling: child-module held via `importlib.import_module` + defensive Dispatch check)*
  - `to_pdf`: normalize inputs; extension gate; default `out_dir = settings.CACHE_DIR / "office_pdf"` (mkdir parents=True); dest `f"{stem}_{sha256(source_bytes)[:8]}.pdf"`; return early if dest exists; try `_com_export(source, dest)` → True returns dest; else `_soffice_export(source, out_dir)` → True: locate `<out_dir>/<stem>.pdf`, overwrite-rename it onto dest, return dest; else `RuntimeError` carrying notebook-style guidance: `No layout engine available to render '<name>' to PDF. Option A: install MS Office; Option B: install LibreOffice (soffice on PATH); Option C: export the PDF yourself and use plain mode instead.`
  - `_com_export`: try `import win32com.client` (ImportError → False); Dispatch per suffix (`docx` Word: `Documents.Open(str(src), ReadOnly=True)` → doc, `SaveAs2(str(dest), 17)`, doc `Close(False)`; `pptx` PowerPoint: `Presentations.Open(str(src.resolve()), True, False, False)` → `SaveAs(str(dest.resolve()), 32)`, `Close()`; `xlsx` Excel: `DisplayAlerts=False`, `Workbooks.Open(str(src.resolve()), 0, True)` → `ExportAsFixedFormat(0, str(dest.resolve()))`, `wb.Close(False)`); `app.Quit()` in finally; any exception → `logger.warning` + False (no dest-verify step needed: bool contract).
  - `_soffice_export`: `_find_soffice()` → `shutil.which("soffice") or shutil.which("soffice.exe")`; None → False; else `subprocess.run([soffice, "--headless", "--norestore", "--convert-to", "pdf", "--outdir", str(out_dir), str(source)], check=True, capture_output=True, timeout=timeout)` → True/False on exceptions (CalledProcessError/Timeout → warning log + False).
  - `available_engine`: try `import win32com.client` → `"com"` (ImportError → None fallthrough); `elif _find_soffice()` → `"soffice"`; else `"none"`.
- [x] **Step 4: Run tests to verify they pass** (all PASS; also rerun `tests/test_markitdown_parser.py` to prove no cross-breakage)
- [x] **Step 5: Commit** `feat: add office_renderer with COM/soffice auto-detect and content-keyed PDF cache`

---

### Task 4: `ParserRouter` mode rewrite (TDD)

**Files:**
- Modify: `src/core/parser_router.py` (full rewrite; decision-table docstring per spec §3)
- Test: `tests/test_parser_router.py` (rewrite)

**Interfaces:**
- Consumes: `MarkItDownParser.parse(...) -> str` (Task 2), `office_renderer.to_pdf(...) -> Path` (Task 3), existing `GLMParser.extract_image/extract_pdf_pages/extract_video`, `is_scanned_pdf` from `src.utils`, `GLMParserError`.
- Produces (Task 5/6 depend on exactly these):
  ```python
  PARSE_MODES: frozenset[str]            # {"auto", "plain", "rendered"}
  def validate_parse_mode(mode: str) -> str   # returns mode; raises ValueError naming PARSE_MODES
  class ParserRouter:
      def __init__(self, markitdown: MarkItDownParser | None = None,
                   glm: GLMParser | None = None) -> None
      def parse(self, info: FileTypeInfo, parse_mode: str = "auto",
                progress: Callable[[int, int], None] | None = None) -> ParseResult
  ParseResult(markdown: str, parser: str, pages: int | None = None)  # shape unchanged
  ```

- [x] **Step 1: Rewrite `tests/test_parser_router.py`** *(implemented per the list; helper `_unconfigured_router` shared by failure tests)*
  - Stubs: `_StubMarkItDown` (`parse(path) -> "md-md"`, records calls), `_StubGLM` (keep today's shape: model_name `"glm-stub"`, extract_image/extract_pdf_pages/extract_video call records). Monkeypatch `router_module.is_scanned_pdf` per test, and `router_module.office_renderer.to_pdf` returning a tmp `.pdf` path.
  - Dispatch-matrix tests (parametrize where uniform): `.md`/`.txt` → passthrough for all 3 modes; `.html`/`.csv` → markitdown in `auto`/`plain`, and markitdown-with-degrade-log in `rendered`; `.docx`/`.pptx`/`.xlsx` → markitdown in `auto`/`plain`, and in `rendered` GLM pdf-pages (path == the stubbed exported pdf) with `pages` == block count (`"<!-- page 1 -->\n\nx"` → 1); born-digital `.pdf` → markitdown (`auto`/`plain`) and GLM (`rendered`); scanned `.pdf` → GLM in `auto` and `rendered`, markitdown in `plain`; image `.png` → GLM image in **plain** too; video → GLM video in all modes.
  - Unconfigured-GLM tests: `auto` + scanned pdf + `_get_glm` raises `GLMParserError` → result from markitdown stub + logger warning (caplog); `rendered` + scanned pdf + same → `pytest.raises(GLMParserError)`; video + same → `pytest.raises(ValueError, match="ZAI_API_KEY")` (today's contract).
  - `test_bad_parse_mode_raises_valueerror` → match `"parse_mode"`.
- [x] **Step 2: Run to verify FAIL** (module still routes on force_vlm / docling)
- [x] **Step 3: Implement the rewrite** per spec §3 decision table:
  - Validate mode first (`validate_parse_mode`).
  - `MARKDOWN/TEXT` → `_passthrough`; `IMAGE`/`VIDEO` → GLM paths unchanged (mode-independent); `HTML/CSV` → markitdown plain (+ `logger.info` "rendered mode not applicable for <ext>, falling back to plain" only when mode == "rendered"); `DOCX/PPTX/XLSX` → `rendered` ? `_via_glm_rendered(path, progress)` : `_via_markitdown(path)`; `PDF` → `_handle_pdf`.
  - `_handle_pdf`: scanned = `is_scanned_pdf(path)`; if mode == "plain" → warn-if-scanned + markitdown; if mode == "auto" and not scanned → markitdown; else (rendered, or auto+scanned) → try `_get_glm()` → `GLMParserError` propagates in `rendered`, but in `auto` is caught → `logger.warning` + markitdown fallback. Success → `_via_glm_pdf(path, progress)`.
  - `_via_glm_pdf`: `markdown = glm.extract_pdf_pages(path, progress)`; pages = `markdown.count("<!-- page ")` or None.
  - `_via_glm_rendered` (office): `pdf = office_renderer.to_pdf(path)`; then same as `_via_glm_pdf` with the **exported** path.
  - `ParseResult.parser`: `"markitdown"` / `"passthrough"` / `glm.model_name`. Docstring decision table copied from spec §3.
- [x] **Step 4: Run to verify PASS** — plus `tests/test_markitdown_parser.py`, `tests/test_office_renderer.py` green. (Other tests may still be red — `src/core/__init__.py` still imports docling; fixed in Task 2's ruling, so the full suite is green here: 237/237.)
- [x] **Step 5: Commit** `refactor: route documents by parse_mode with markitdown plain + GLM rendered paths`

---

### Task 5: Converter service, core exports, docling removal (TDD where testable)

**Files:**
- Modify: `src/core/converter.py` (imports; `parse_mode` threading; except tuple)
- Modify: `src/core/__init__.py` (export swap: `MarkItDownParser`, `MarkItDownParserError` for the Docling pair)
- Modify: `src/chunking/metadata.py:14` (docstring value `"docling"` → `"markitdown"`)
- Modify: `tests/test_metadata.py:90,96` (example `parser="docling"` / assertion → `"markitdown"`)
- Modify: `app.py:22` (warm-up log: `"Initializing document converter..."` — no Docling mention)
- Delete: `src/core/docling_parser.py`
- Test: `tests/test_converter.py` (new)

**Interfaces:**
- Consumes: `validate_parse_mode` (Task 4), `MarkItDownParserError` (Task 2), everything else unchanged.
- Produces: `MarkdownConverterService.convert(file_path, parse_mode="auto", progress=None) -> str`; `convert_detailed(file_path, parse_mode="auto", progress=None) -> ConversionOutput`; `convert_and_save(file_path, output_path=None, parse_mode="auto") -> Path`; `IngestionPipeline.ingest(..., parse_mode)` (Task 6). `ConversionOutput` shape unchanged.

- [x] **Step 1: Write `tests/test_converter.py`**
  - `test_bad_parse_mode_raises_eagerly` — `pytest.raises(ValueError, match="parse_mode")` on `convert_detailed(path, parse_mode="turbo")`; no conversion runs.
  - `test_csv_end_to_end` — real tmp CSV through `convert_detailed`: markdown contains `"|"`, `parser == "markitdown"`, `pages is None`, file_info format `csv`.
- [x] **Step 2: Run to verify FAIL** (arg missing; and import of `src.core` still broken at this point — the fix lands together) *(actual red: `TypeError: unexpected keyword parse_mode` — the import chain was already green via Task 2's ruling)*
- [x] **Step 3: Implement** *(core/__init__ swap, docling_parser deletion, preloader block were already landed by Task 2's ruled decoupling; converter threading + metadata/app.py swaps done here)*
  - converter: `from .parser_router import validate_parse_mode`; `from .markitdown_parser import MarkItDownParserError`; every public conversion method validates `parse_mode` first, then threads it to `_router.parse(info, parse_mode=... , progress=...)`; except tuple `(MarkItDownParserError, GLMParserError)`; generic handler stays.
  - `src/core/__init__.py`: swap docling imports/exports for the MarkItDown pair.
  - Delete `src/core/docling_parser.py`, and in the same edit remove the Docling block from `scripts/preload_models.py` (it imports the deleted module; keep its FlashRank + FastEmbed parts).
  - metadata docstring + test example swaps; app.py log text.
- [x] **Step 4: Run the FULL suite** `.venv\Scripts\python.exe -m pytest tests/ -v` → **all green** (239/239)
- [x] **Step 5: Commit** `refactor: thread parse_mode through converter service; markitdown provenance`

---

### Task 6: Ingestion pipeline threading

**Files:**
- Modify: `src/indexing/pipeline.py:61-96` (`ingest` signature + converter call)

**Interfaces:**
- Consumes: `MarkdownConverterService.convert_detailed(..., parse_mode="auto", ...)` (Task 5).
- Produces: `IngestionPipeline.ingest(file_path, *, parse_mode="auto", replace_existing=True, skip_if_exists=False, ocr_progress=None) -> IngestionResult`.

- [x] **Step 1: Edit `ingest`** — add `parse_mode="auto"` keyword-only param; pass `parse_mode=parse_mode` into `convert_detailed`; log parser readiness changes only. No behavioral tests here (router/converter tests own behavior; pipeline has none today).
- [x] **Step 2: Verify** `.venv\Scripts\python.exe -m pytest tests/ -q` → all green, no regressions (239/239).
- [x] **Step 3: Commit** `feat: thread parse_mode through ingestion pipeline`

---

### Task 7: UI (Convert + Ingest radios, engine note, footer)

**Files:**
- Modify: `src/ui/markdown_converter_ui.py` (checkbox → radio; explainer; engine note; status gains no new fields)
- Modify: `src/ui/ingest_ui.py` (same radio; threads into `pipeline.ingest`)
- Modify: `src/ui/main_ui.py:43` (footer: "Powered by MarkItDown & GLM-5.3-Flash")

**Interfaces:**
- Consumes: `MarkdownConverterService.convert_detailed(..., parse_mode=...)` (Task 5); `IngestionPipeline.ingest(..., parse_mode=...)` (Task 6); `from src.core.office_renderer import available_engine` (Task 3); `GLMParser.is_configured()`.
- Produces: Gradio callbacks wired exactly as before (`file_input.change`, button clicks) with `gr.Radio(choices=["auto", "plain", "rendered"], value="auto", label="Processing mode")` replacing both checkboxes.

- [x] **Step 1: Modify `markdown_converter_ui.py`**
  - Replace the `force_vlm` Checkbox with a three-way `gr.Radio` using (label, value) tuple choices exactly: `("Auto (default)", "auto")`, `("Plain (MarkItDown)", "plain")`, `("Rendered + LLM (GLM)", "rendered")`, label `"Processing mode"`, `info=` text summarizing: auto=plain conversion, vision OCR only for scanned PDFs; plain=direct conversion, no API cost; rendered=page images → GLM OCR (slower, costs Z.ai tokens; needs MS Office or LibreOffice).
  - Explainer markdown: MarkItDown for `.pdf`/`.docx`/`.pptx`/`.xlsx`/`.html`/`.csv`; GLM-5.3-Flash for images, scanned PDFs, videos; passthrough `.md`/`.txt`; plus the honesty note "Images and videos always use GLM — they have no plain path."
  - Engine-status line under the accordion: `f"_Rendered-mode engine: {available_engine()} — ..."`.
  - `_convert_document(file_info, parse_mode, progress)` signature + forward.
- [x] **Step 2: Modify `ingest_ui.py`** identically (radio in place of `force_vlm`; `pipeline.ingest(..., parse_mode=...)`).
- [x] **Step 3: Footer** — swap the Docling link/brand for MarkItDown (keep GLM link).
- [x] **Step 4: Verify import smoke**
  ```powershell
  .venv\Scripts\python.exe -c "import src.ui.main_ui, src.ui.ingest_ui, src.ui.markdown_converter_ui; print('ui ok')"
  ```
  Expected: `ui ok` (browser rendering stays manual for the owner).
- [x] **Step 5: Commit** `feat: expose auto/plain/rendered processing mode in Convert and Ingest tabs`

---

### Task 8: Docs, Docker, preload, and docling-sweep

**Files:**
- Modify: `Dockerfile` (builder-stage comments: drop "Pre-download Docling models" wording; keep FlashRank/FastEmbed parts and env vars)
- Modify: `README.md` (lines ≈36/38 table, 60 parser sample, 131 module tree, 201 first-run note, 259/260 phase log wording)
- Modify: `docs/ARCHITECTURE.md` (69 diagram, 112 tech table, 161 tree, 163 caption, 229/234 flow branches, 239 heuristic paragraph, 248 sentence, 291 sample, 626 comparison row "Document parser | Docling" → MarkItDown)
- Modify: `.env.example` — GLM comment: "also powers office 'rendered' mode OCR"
- Delete: `docs/DOCLING_MODELS.md`
- (Task 5 already handled `scripts/preload_models.py`.)

**Interfaces:** Consumes nothing beyond prior tasks; Produces an externals-consistent repo.

- [x] **Step 1: Sweep every docling mention** in the files above with the spec's replacements (Docling→MarkItDown; module tree entry `docling_parser.py` → `markitdown_parser.py` + add `office_renderer.py`; parser sample → `"markitdown"`; first-run note loses the ~1-2 GB Docling model sentence; heuristic paragraph drops the Docling-EasyOCR comparison and instead contrasts plain vs rendered modes).
- [x] **Step 2: Grep gate**
  ```powershell
  Select-String -Path src\*,tests\*,scripts\*,app.py,Dockerfile,pyproject.toml,requirements.txt -Pattern docling -SimpleMatch
  ```
  Expected: zero hits. (Historical docs like git reports, `docs/superpowers/` specs/plans from prior migrations, and this migration's own docs are excluded.) *(Gate output: 0; ARCHITECTURE.md decision-log retains two historical mentions — excluded per the gate.)*
- [x] **Step 3: Commit** `docs: rebrand document parsing around markitdown and drop docling plumbing`

---

### Task 9: Final gates + push

**Files:** none new; repo state check.

- [x] **Step 1: Full suite** `.venv\Scripts\python.exe -m pytest tests/ -v` → all PASS. (239/239)
- [x] **Step 2: Service smoke with a real file** *(output: `markitdown | 1` — exact expected)*
- [x] **Step 3: Lockfile consistency** — `uv lock --check` exits 0.
- [x] **Step 4: Push** `git push origin feat/docling-to-markitdown-migration` (no merge — owner merges).
- [ ] **Step 5: Report back** — summary of tasks completed, remaining manual checks for the owner: Convert tab (docx/pptx/xlsx plain + rendered with real Office COM; scanned + born-digital PDFs), Ingest tab radios, re-ingest cache behavior. *(happens in the agent's final message after whole-branch review)*
