# Design: Replace Docling with MarkItDown + dual-mode (plain / rendered→GLM) ingestion

**Date:** 2026-10-16
**Status:** Approved design — pending implementation plan
**Branch:** `feat/docling-to-markitdown-migration`
**Anchor:** `markitdown/notebook.ipynb` (the owner's verified experiment notebook)

---

## 1. Context

AdaptiveRAG converts uploaded files to markdown, chunks them, and indexes them into a hybrid
(dense + sparse) Qdrant collection. Today the parser router owns four conversion paths:

1. **Passthrough** (`.md`, `.txt`)
2. **DoclingParser** — born-digital PDF, DOCX, PPTX, XLSX, HTML, CSV
3. **GLMParser** (Z.ai GLM-5.3-Flash vision) — images, scanned PDFs (rendered page OCR,
   SHA256-keyed disk cache, retry), videos
4. **Fallbacks** — scanned PDF with GLM unconfigured falls back to Docling

Docling is heavy (torch, HuggingFace layout/TableFormer model downloads, Docker preload
machinery) while Microsoft's **MarkItDown** covers the same digital formats with plain
library code. The owner has already removed docling dependencies, created a fresh venv,
and opened this branch.

The owner's notebook (`markitdown/notebook.ipynb`) validates each behavior we adopt:

- Plain `MarkItDown()` conversion for DOCX (Mammoth HTML→Markdown), PDF text layer via
  pdfminer, PPTX per-slide sections, XLSX pipe tables per sheet, CSV pipe tables.
- MarkItDown's built-in LLM hooks apply **only** to image files and embedded PPTX pictures;
  the PDF/DOCX/XLSX converters ignore `llm_*` kwargs entirely (verified empirically) — so
  the app does **not** use MarkItDown's LLM features at all.
- The proven render→OCR→stitch pipeline: layout-engine export to PDF → render pages to PNG →
  vision call per page → stitch `<!-- page NN -->` blocks joined by `\n\n---\n\n` — with
  Office COM (Word `SaveAs2`–docx, PowerPoint `SaveAs(32)`–pptx, Excel
  `ExportAsFixedFormat(0)`–xlsx) auto-detected before a LibreOffice `soffice --headless
  --norestore --convert-to pdf` fallback, and a clear manual-export error otherwise.

### Decisions (owner-confirmed 2026-10-16)

1. **Rendered-path OCR runs on the existing GLMParser** (Z.ai GLM-5.3-Flash) — not the
   notebook's OpenAI `gpt-6-luna`. GLMParser already provides SHA-keyed caching, retries,
   page-block stitching, and provenance.
2. **CSV gets no rendered path** — plain MarkItDown only. CSV is pure data; vision would
   re-transcribe the same numbers expensively.
3. **Rendered path is local-first** — MS Office COM on the owner's Windows machine,
   LibreOffice fallback; Docker/HF Spaces stays plain-only (honestly surfaced in the UI).
   No LibreOffice in the Dockerfile.
4. Implementation follows **Approach A**: keep the single `ParserRouter`, swap
   `DoclingParser` out, thread a `parse_mode` through the existing call chain.

---

## 2. Goals / Non-goals

**Goals**

1. All document format conversions migrate off Docling: born-digital PDF, DOCX, PPTX,
   XLSX, CSV, HTML → MarkItDown plain conversion.
2. Every paginated format (DOCX, PPTX, XLSX, PDF both variants) supports an explicit
   **rendered + LLM** mode: export to PDF (office only) → `pypdfium2` page rendering →
   GLM page OCR → stitched page blocks.
3. A user-selectable `parse_mode` (`auto` | `plain` | `rendered`) replaces both the
   `force_vlm_for_pdf` checkbox and its implicit semantics, exposed in Convert and Ingest
   tabs as a 3-way radio.
4. Zero docling remnants: parser module, exports, UI copy, footer, preload script,
   Dockerfile comments, README, ARCHITECTURE.md, metadata docstrings, tests,
   `langchain-docling` dep, `docs/DOCLING_MODELS.md`.
5. Re-ingest efficiency: exported office PDFs are content-keyed on disk so repeated
   ingestion of an unchanged file produces GLM cache hits with no re-export.

**Non-goals**

- No MarkItDown LLM integration (`llm_client`/`llm_model`) — our vision path is GLMParser.
- No PyMuPDF — `pypdfium2` remains the rasterizer (scale 2.0 ≈ 144 DPI, as today).
- No Configurable-OCR-backend abstraction (single backend: Z.ai).
- No LibreOffice/Office inside the Docker image (plain mode only in containers).
- No change to chunking, indexing, retrieval, synthesis, routing, or SQL layers.
- No browser/Playwright UI tests (owner runs the app manually and reports back).

---

## 3. Routing & mode semantics

`force_vlm_for_pdf: bool` → `parse_mode: Literal["auto", "plain", "rendered"]`,
threaded converter → router. Bad value → immediate `ValueError` naming the three options.

Decision table (router):

| File | `auto` (default) | `plain` | `rendered` |
|---|---|---|---|
| `.md` / `.txt` | passthrough | passthrough | passthrough (no pages to render) |
| `.html` | markitdown plain | markitdown plain | markitdown plain + logged degrade note |
| `.csv` | markitdown plain | markitdown plain | markitdown plain + logged degrade note |
| `.docx` / `.pptx` / `.xlsx` | markitdown plain | markitdown plain | export→PDF → render → GLM OCR |
| `.pdf` born-digital | markitdown plain | markitdown plain | render → GLM OCR |
| `.pdf` scanned (heuristic) | render → GLM OCR | markitdown plain (+ warning logged) | render → GLM OCR |
| `.png` / `.jpg` / `.jpeg` / `.webp` | GLM image | GLM image | GLM image |
| `.mp4` / `.mkv` / `.mov` | GLM video | GLM video | GLM video |

Principles:

- Images/videos have no plain alternative and always use GLM regardless of mode; the radio
  governs documents only (stated in the UI).
- `auto` keeps today's heuristic (`is_scanned_pdf`: <150 extractable text chars across the
  first 3 sampled pages).
- Degradation (html/csv in `rendered` mode; text files passthrough) logs a note; no extra
  error-shape fields are added to results.
- Provenance values for `ParseResult.parser` / metadata: `"markitdown"`, `"passthrough"`,
  or the resolved GLM model code (e.g. `"glm-5.3-flash"`); `pages` stays None except
  page-OCR paths (scanned PDF, rendered office), which count `<!-- page ` blocks.

---

## 4. Detailed changes

### 4.1 New: `src/core/markitdown_parser.py`

Replaces `src/core/docling_parser.py` (deleted). Same thin-wrapper shape.

```python
class MarkItDownParserError(Exception): ...

class MarkItDownParser:
    def __init__(self) -> None            # one MarkItDown(enable_plugins=False) instance
    def parse(self, file_path) -> str
```

- `FileNotFoundError` re-raised as-is (docling wrapper parity).
- `FileConversionException` / `MissingDependencyException` (and any converter crash) wrap
  into `MarkItDownParserError` carrying the filename.
- Empty markdown logs a warning and returns `""`; non-empty logs `n chars` at INFO.
- No `warm_up()` — MarkItDown is model-free; nothing to preload.

### 4.2 New: `src/core/office_renderer.py`

The notebook's `docx_to_pdf` / `pptx_to_pdf` / `xlsx_to_pdf` collapsed into one function.

```python
def to_pdf(file_path: Path, out_dir: Path) -> Path   # exported PDF path
def available_engine() -> str                        # "com" | "soffice" | "none"
```

- Engine precedence exactly per notebook: Office COM via `pywin32` first
  (Word COM `Documents.Open(ReadOnly=True)` → `SaveAs2(path, 17)`;
  PowerPoint `Presentations.Open(...).SaveAs(path, 32)`; Excel
  `Workbooks.Open(UpdateLinks=0, ReadOnly=True)` → `ExportAsFixedFormat(0, path)`;
  COM objects closed and `App.Quit()` in `finally`), LibreOffice
  `soffice --headless --norestore --convert-to pdf --outdir <out_dir>` second
  (located via `shutil.which("soffice" | "soffice.exe")`, 600 s timeout),
  then `RuntimeError` with Option A/B/C guidance (install Office / install LibreOffice /
  export manually + switch modes).
- Destination filename: `<stem>_<first 8 hex of sha256(source bytes)>.pdf` under
  `settings.CACHE_DIR / "office_pdf"`. **Skip if the file exists** — deterministic naming
  + skip-if-exists makes repeated ingestion produce byte-identical page PNGs, which keys
  GLM's OCR cache → zero API calls on re-ingest of unchanged files.
- `available_engine()` powers the UI's honest capability note without side effects.

### 4.3 Modified: `src/core/parser_router.py`

```python
ParseMode = Literal["auto", "plain", "rendered"]
ParseResult(markdown, parser, pages)          # shape unchanged

class ParserRouter:
    def __init__(self, markitdown: MarkItDownParser | None = None,
                 glm: GLMParser | None = None) -> None
    def parse(self, info, parse_mode="auto", progress=None) -> ParseResult
```

- Lazy init preserved (`_get_markitdown`, `_get_glm`) — same stub-injection seams tests
  use today.
- New glue: `_via_glm_rendered(path, progress)` — `office_renderer.to_pdf` unless
  already PDF, then `glm.extract_pdf_pages(pdf, progress)`, page count via block count.
- `auto` + scanned PDF + GLM unconfigured → falls back to **plain markitdown** with a
  logged warning (replaces the docling fallback; weak-but-something beats hard failure).
- `rendered` mode with GLM unconfigured → hard `GLMParserError` (explicit opt-in fails
  loudly, no silent downgrade).
- Video unconfigured keeps today's `ValueError` with `ZAI_API_KEY` guidance.

### 4.4 Modified: `src/core/converter.py` · `src/core/__init__.py`

- `convert_detailed(..., parse_mode="auto")`; `convert()` forwards; `convert_and_save`
  passes mode too. Validation eager at the service so bad values never reach parsers.
- Caught parser errors: `(MarkItDownParserError, GLMParserError)` →
  `DocumentConverterError`; layout-engine `RuntimeError` also wrapped (message intact).
- `__init__.py` exports: `MarkItDownParser`, `MarkItDownParserError` in place of the
  Docling pair.

### 4.5 Modified: `src/indexing/pipeline.py`

`IngestionPipeline.ingest(..., parse_mode="auto")` forwards to the converter; everything
else (doc_id, skip logic, metadata build, chunking, upsert) untouched.

### 4.6 UI changes

`src/ui/markdown_converter_ui.py`:

- Checkbox → `gr.Radio(["auto", "plain", "rendered"], value="auto")` with labels:
  `Auto (default)`, `Plain (MarkItDown)`, `Rendered + LLM (GLM)` and per-option info text
  (Section 3 table, in user-facing words).
- Top explainer lists MarkItDown / GLM / passthrough per format; note "Images and videos
  always use GLM — they have no plain path."
- Engine-status line: `available_engine()` → "MS Office COM ready" / "LibreOffice
  available (soffice)" / "No layout engine found — install MS Office or LibreOffice
  (soffice on PATH) to enable Rendered mode".
- Status block keeps parser + page count; `parse_mode` replaces the checkbox input.

`src/ui/ingest_ui.py`: same radio, threaded into `pipeline.ingest(..., parse_mode=...)`.

`src/ui/main_ui.py` footer: "Powered by Docling" → "Powered by MarkItDown &
GLM-5.3-Flash (Z.ai)".

### 4.7 Cleanup & infrastructure

| File | Change |
|---|---|
| `src/core/docling_parser.py` | delete |
| `docs/DOCLING_MODELS.md` | delete |
| `scripts/preload_models.py` | drop Docling section; keep FlashRank + FastEmbed preload |
| `Dockerfile` | update preload-stage comments (no Docling downloads; image gets lighter); keep harmless HF env vars |
| `src/chunking/metadata.py` | docstring parser values `"docling"` → `"markitdown"` |
| `app.py` | warm-up log text (no Docling mention) |
| `README.md`, `docs/ARCHITECTURE.md` | parsers table / module tree / provenance → MarkItDown |
| `.env.example` | GLM comment: now also powers office `rendered` mode |
| `pyproject.toml` | remove `langchain-docling`; add `pywin32; sys_platform == 'win32'`; keep `markitdown[all]`, `pypdfium2` |
| `requirements.txt` | same two edits |
| Lockfiles | re-lock (`uv lock`, regenerate requirements) |

### 4.8 Testing

1. `tests/test_parser_router.py` — rewritten dispatch matrix around `_StubMarkItDown` /
   `_StubGLM`: full format × mode table, heuristic monkeypatched both directions, bad
   mode → `ValueError`, auto+scanned+unconfigured → plain fallback (+warning),
   rendered+unconfigured → error, video path unchanged.
2. `tests/test_markitdown_parser.py` (new) — one real offline conversion (tiny CSV → pipe
   table) proving the wrapper end-to-end; monkeypatched `MarkItDown` for
   exception-wrapping and empty-output rows.
3. `tests/test_office_renderer.py` (new) — COM→soffice→error precedence with stubbed
   `shutil.which` + fake `win32com` module; per-app format codes asserted (17/32/0);
   content-hash filename; skip-if-exists reuse; soffice timeout honored.
4. `tests/test_metadata.py` — parser example values updated.
5. Existing `test_file_detector.py`, `test_ocr_cache.py`, `test_glm_parser.py` untouched.

## 5. Verification

Automated gates (agent-run, no browser):

1. Full `pytest` suite green.
2. Import smoke: service construction + router spot-call with a tiny CSV in-process.
3. `grep -ri docling` over `src/`, `tests/`, `scripts/`, `app.py`, `Dockerfile`,
   `pyproject.toml`, `requirements.txt` → zero hits (historical docs/reports excluded).
4. Lockfiles regenerated and consistent.

Owner-run verification (manual, after the agent pass — no browser automation):
Convert + Ingest tabs against real files, exercising Office COM rendered mode
(docx/pptx/xlsx + complex-layout PDF), Core-scanned and born-digital PDFs, and confirming
re-ingest cache behavior. Owner merges the branch; agent does **not** merge.
