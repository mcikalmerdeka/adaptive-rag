# AdaptiveRAG — Docling Model Cache Audit

An audit of the Docling model artifacts downloaded to the dev machine: what was
downloaded, why, the actual model sizes vs. the disk footprint, and two findings
that affect processing speed and Docker cold-start behavior.

Snapshot: **2026-10-12** · docling **2.92.0** · Python **3.14.3** (`.venv`) · Windows dev machine.

---

## Table of Contents

1. [Where the models live](#1-where-the-models-live)
2. [Inventory](#2-inventory)
3. [Why several models — and why not one per document format](#3-why-several-models--and-why-not-one-per-document-format)
4. [Why the disk footprint exceeds the models](#4-why-the-disk-footprint-exceeds-the-models)
5. [Speed finding: OCR runs on every PDF page](#5-speed-finding-ocr-runs-on-every-pdf-page)
6. [Cleanup options (~537 MB reclaimable)](#6-cleanup-options-537-mb-reclaimable)
7. [Docker image note: the preload script is a no-op for Docling](#7-docker-image-note-the-preload-script-is-a-no-op-for-docling)
8. [Environment facts](#8-environment-facts)

---

## 1. Where the models live

Docling resolves its models through `huggingface_hub` (`snapshot_download`). With
no `artifacts_path` configured and no `DOCLING_ARTIFACTS_PATH` env var (both
verified unset), artifacts land in the shared Hugging Face hub cache instead of a
Docling-specific folder:

| Location | Contents |
|---|---|
| `~/.cache/huggingface/hub/models--docling-project--docling-layout-heron` | PDF layout detector |
| `~/.cache/huggingface/hub/models--docling-project--docling-models` | TableFormer table-structure models (both variants) |
| `~/.EasyOCR/model/` | EasyOCR OCR engine models (orphaned — see §4) |
| `~/.cache/huggingface/hub/models--Systran--faster-whisper-base` | Docling ASR pipeline model (orphaned — see §4) |

The legacy `~/.Docling` folder does not exist (that was Docling v1's location).

**Windows symlink note.** `src/core/docling_parser.py:17` sets
`HF_HUB_DISABLE_SYMLINKS=1` (to avoid WinError 1314, which requires admin rights
or Developer Mode). Consequence: each cached revision is stored as a **full
copy** rather than a symlink to a shared blob — the `blobs/` directory stays
nearly empty and every snapshot revision costs the full model size again. This
is why an old revision is not "free".

## 2. Inventory

| Model | File | Size | Role | Status |
|---|---|---|---|---|
| Layout detector (Heron) | `docling-layout-heron` → `model.safetensors` | **163.71 MB** per revision | Detects headings / paragraphs / tables / figures on PDF page images | ✅ used (revision `8f39ad3c…`, Apr 30 2026) |
| ↳ stale duplicate revision | same repo, revision `54100ede…` | 163.71 MB | Same model, older pinned revision (downloaded Jan 15 2026) | ⚠️ **orphan** — `refs/main` points to the Apr revision |
| TableFormer **accurate** | `docling-models` (ref `v2.3.0`) → `model_artifacts/tableformer/accurate/tableformer_accurate.safetensors` | **202.90 MB** | Reconstructs table grids + cell relationships | ✅ used — default `TableFormerMode.ACCURATE` (`pipeline_options.py:141`) |
| TableFormer **fast** | same repo → `model_artifacts/tableformer/fast/tableformer_fast.safetensors` | **138.72 MB** | Faster/less accurate TableFormer variant | ⚠️ **never used** — bundled in the same repo snapshot and swept along |
| EasyOCR detector | `~/.EasyOCR/model/craft_mlt_25k.pth` | **79.30 MB** | Text region detection (multilingual) | ⚠️ **orphan** — `easyocr` is not installed in the current `.venv` |
| EasyOCR recognizer | `~/.EasyOCR/model/english_g2.pth` | **14.44 MB** | English text recognition | ⚠️ **orphan** — same reason |
| faster-whisper-base | hub cache `models--Systran--faster-whisper-base` | **141.0 MB** | Docling audio/ASR pipeline | ⚠️ **orphan** — `faster-whisper` is not a project dependency; AdaptiveRAG has no ASR path (video goes through GLM vision frames) |

**Disk footprint vs. what is actually needed:**

| | Size |
|---|---|
| Docling-related artifacts on disk (HF hub: 327.6 + 341.6 = 669.2 MB, plus EasyOCR 93.7 MB) | **≈ 763 MB** |
| Required at runtime with current settings (Heron + TableFormer accurate) | **≈ 367 MB** (+ OCR engine models, engine auto-selected at runtime) |
| Reclaimable (stale Heron revision + TableFormer fast + EasyOCR + faster-whisper) | **≈ 537 MB** |

Notably absent (and not needed by the defaults): the CodeFormula model
(`do_code_enrichment`/`do_formula_enrichment` are `False` by default), the newer
`docling-layout-egret-*` models, and SmolDocling — the standard pipeline never
fetches them.

## 3. Why several models — and why not one per document format

**The key misconception to clear up: Docling does not download models "per
document converter type".** The model set is per-capability *within the PDF
pipeline*, not per format:

| Pipeline stage | Model | What it does |
|---|---|---|
| Layout analysis | Heron (DocLayNet-trained detector) | Where each heading, paragraph, table, and figure is on the page |
| OCR | Auto-selected engine (see §5) | Reads text from page pixels |
| Table structure | TableFormer | Rebuilds row/column relationships into a logical table |

- **Only PDF (and image) conversions touch the model stack.** DOCX, PPTX, XLSX,
  HTML, and CSV are parsed by rule-based native parsers (`docling-parse`,
  `docling-core`) — those conversions download **zero** models.
- All model downloads observed here happened on the **first PDF conversion**
  (Jan 15 2026 timestamps) — Docling initializes its PDF pipeline lazily on the
  first PDF, not at `DocumentConverter()` construction (verified in
  `docling/document_converter.py`: `__init__` never calls
  `initialize_pipeline`; that happens on first convert).

## 4. Why the disk footprint exceeds the models

Three compounding causes:

1. **Stale Heron revision (~164 MB).** A docling upgrade between Jan and Apr
   2026 re-pinned the layout model revision, so the same 164 MB model was
   downloaded a second time. Because `HF_HUB_DISABLE_SYMLINKS=1` forces copies
   (§1), the old revision is not deduplicated and stays on disk forever.
2. **TableFormer fast (139 MB).** Docling fetches TableFormer from the legacy
   consolidated `docling-models` repository, whose snapshot contains *both*
   variants; the snapshot download sweeps the unused `fast` weights along.
3. **Leftover EasyOCR models (94 MB) + faster-whisper-base (141 MB).** The
   current venv has no `easyocr` package — docling ≥ 2.92 splits into
   `docling-slim` (no heavy OCR extra) and the default `ocr_engine` is
   `OcrAutoOptions()` (`pipeline_options.py:1555`), which auto-selects an
   installed engine (RapidOCR 3.8.1 is installed). The `~/.EasyOCR` models are
   residue from an older environment. faster-whisper-base was likely fetched
   during an ASR experiment; no project code can import it.

## 5. Speed finding: OCR runs on every PDF page

Verified defaults in the installed docling 2.92.0
(`datamodel/pipeline_options.py`):

- `do_ocr = True` (line 1500) — and the field docstring warns *"OCR
  significantly increases processing time."*
- `do_table_structure = True`
- `ocr_engine = OcrAutoOptions()` (line 1555) — auto-selects based on
  availability; with `easyocr` absent and `rapidocr` installed, RapidOCR is the
  engine in use.

The project creates a bare `DocumentConverter()` with no pipeline options
(`src/core/docling_parser.py:33`), so **every PDF page — including born-digital
ones that already have a perfect embedded text layer — goes through OCR.**

Given the parser architecture, this is pure overhead: `src/core/parser_router.py`
routes scanned/image PDFs to the GLM vision parser, so Docling only ever sees
born-digital PDFs. Disabling docling-side OCR removes per-page OCR work entirely
while keeping layout + TableFormer:

```python
# src/core/docling_parser.py — __init__
from docling.datamodel.base_models import InputFormat
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.datamodel.pipeline_options import PdfPipelineOptions

options = PdfPipelineOptions()
options.do_ocr = False  # born-digital PDFs only; scanned ones route to GLM vision

self._converter = DocumentConverter(
    format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)}
)
```

Caveat: if scanned PDFs are ever routed *back* to Docling, re-enable `do_ocr`.

## 6. Cleanup options (~537 MB reclaimable)

Optional — the stale artifacts are never requested again; if a future docling
version ever needs a removed file it will simply re-download it. After any
cleanup, run one PDF conversion end-to-end to confirm the remaining models load.

```powershell
$hub = "$env:USERPROFILE\.cache\huggingface\hub"

# 1) Stale layout-model revision (~164 MB) — refs/main points to the Apr 2026 revision
Remove-Item -Recurse -Force "$hub\models--docling-project--docling-layout-heron\snapshots\54100edecdceb65a9d8204d2478ac4cc8d4ca68b"

# 2) TableFormer fast (~139 MB) — never used, default mode is ACCURATE
Remove-Item -Recurse -Force "$hub\models--docling-project--docling-models\snapshots\fc0f2d45e2218ea24bce5045f58a389aed16dc23\model_artifacts\tableformer\fast"

# 3) EasyOCR models (~94 MB) — easyocr is not installed; the auto engine resolves to RapidOCR
Remove-Item -Recurse -Force "$env:USERPROFILE\.EasyOCR"

# 4) faster-whisper-base (~141 MB) — no ASR path exists in this project
Remove-Item -Recurse -Force "$hub\models--Systran--faster-whisper-base"
```

## 7. Docker image note: the preload script is a no-op for Docling

`scripts/preload_models.py` claims to pre-download Docling models during the
Docker build ("Docling models cached."), but it only constructs
`MarkdownConverterService()`, which builds a `FileTypeDetector` and a lazy
`ParserRouter` (`src/core/converter.py:43-46`). No conversion runs, no pipeline
is initialized, **no Docling model is downloaded** — the built image still pays
the full cold-start model download on the first PDF conversion. The FlashRank
and FastEmbed BM25 steps in the same script *do* work (their constructors fetch
their models).

Minimal fix — explicitly initialize the PDF pipeline (this is what downloads
the layout + TableFormer models):

```python
# scripts/preload_models.py — replace the Docling block
from docling.datamodel.base_models import InputFormat
from src.core.docling_parser import DoclingParser

parser = DoclingParser()
parser._converter.initialize_pipeline(InputFormat.PDF)
```

(Optionally wrap this as a public `DoclingParser.warm_up()` method instead of
reaching into the private converter.) With `do_ocr = False` (§5) applied first,
the OCR engine stage downloads nothing extra.

## 8. Environment facts

| Component | Version |
|---|---|
| docling | 2.92.0 (meta package; `docling-slim` 2.92.0 carries the runtime) |
| docling-core | 2.74.1 |
| docling-ibm-models | 3.13.2 (TableFormer, layout, OCR model zoo) |
| docling-parse | 5.10.1 (native PDF parser backend) |
| langchain-docling | 2.0.0 |
| OCR engine in venv | RapidOCR 3.8.1 + onnxruntime 1.25.1 (EasyOCR absent) |
| torch | 2.11.0 (via docling-ibm-models) |
| Python | 3.14.3 |
| Model cache | HF hub cache (`~/.cache/huggingface/hub`), symlinks disabled |
