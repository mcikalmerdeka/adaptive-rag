# AdaptiveRAG — Project Plan & Progress Tracker

> Master checklist for the entire build. Update status markers as work completes. See `ARCHITECTURE.md` for design rationale.

**Status legend:** ✅ done · 🚧 in progress · ⬜ pending · ⏸️ deferred · ❌ cancelled

---

## Phase 0 — Project Setup ✅

- [x] Repo initialized (`.git`, `.gitignore`, `.gitattributes`)
- [x] Python 3.14 + `uv` package manager
- [x] `pyproject.toml` with core deps
- [x] `.env` for API keys (`OPENAI_API_KEY`, `QWEN_API_KEY`)
- [x] `AGENTS.md` engineering principles
- [x] `ARCHITECTURE.md` system design
- [x] `PROJECT_PLAN.md` (this file)
- [ ] `.env.example` template

---

## Phase 1 — Document → Markdown (Docling baseline) ✅

**Goal:** Upload a document, get clean markdown back. Docling-only.

- [x] `src/core/file_detector.py` — extension/MIME detection
- [x] `src/core/converter.py` — Docling wrapper
- [x] `src/ui/markdown_converter_ui.py` — Gradio upload/preview/download UI
- [x] `app.py` — entry point
- [x] Docling model warm-up on startup

**Acceptance:** Upload PDF/DOCX/PPTX, see markdown rendered, download `.md` file.

---

## Phase 2 — Parser Router + Qwen3-VL OCR Fallback 🚧

**Goal:** Route per-file-type. Use Docling for digital formats, Qwen3-VL for images and scanned PDFs. Add caching so iteration doesn't burn API credits.

### Cleanup

- [ ] Trim `file_detector.py` to common formats only (drop ASCIIDOC, LaTeX, XML, JSON, audio/video, VTT, BMP, TIFF, format variants like `.dotx`/`.docm`/etc.)

### New modules

- [ ] `src/utils/pdf_inspector.py`
  - [ ] `is_scanned_pdf(path) -> bool` heuristic (sample first 3 pages, threshold by extracted text length)
  - [ ] `render_pdf_pages(path, dpi=150) -> Iterator[bytes]` (PNG bytes via `pypdfium2`)
- [ ] `src/cache/ocr_cache.py` — SHA256-keyed disk cache for OCR results
- [ ] `src/core/qwen_parser.py`
  - [ ] `QwenParser.extract_image(path) -> str`
  - [ ] `QwenParser.extract_pdf_pages(path) -> str` (per-page caching, concat)
  - [ ] Tenacity retry on rate limits / network errors
  - [ ] Deterministic OCR prompt
- [ ] `src/core/docling_parser.py` — Docling-only parser (extracted from `converter.py`)
- [ ] `src/core/parser_router.py` — dispatches:
  ```
  .md / .txt           → passthrough (read file)
  .png / .jpg / .webp  → Qwen
  .pdf scanned         → Qwen (per page, cached)
  .pdf born-digital    → Docling
  .docx / .pptx / .xlsx / .html / .csv → Docling
  ```

### Refactor

- [ ] `src/core/converter.py` — slim down to public API, delegate to `parser_router`
- [ ] `src/core/__init__.py` — update exports

### UI

- [ ] Toggle: "Force Qwen3-VL OCR for PDFs" (override born-digital heuristic)
- [ ] Progress indicator for multi-page scanned PDFs
- [ ] Show parser used (`docling` / `qwen3-vl` / `passthrough`) in status

### Dependencies

- [ ] Add `pypdfium2>=4.30` (PDF inspection + rendering)
- [ ] Add `tenacity>=9.0` (retry)
- [ ] Add `pillow>=10` (PIL image handling — also Docling transitive but pin explicit)

**Acceptance:**
1. Upload a born-digital PDF → routes to Docling → markdown returned in seconds.
2. Upload a scanned PDF → routes to Qwen → markdown with preserved tables.
3. Upload a `.png` of a table → routes to Qwen → markdown table.
4. Re-upload same file → returns from cache (< 100ms, no API call).
5. Upload `.docx` / `.pptx` / `.xlsx` / `.html` → Docling, no Qwen call.
6. Upload `.md` / `.txt` → passthrough, instant.

---

## Phase 3 — Chunking + Indexing ✅

**Goal:** Header-aware chunking + hybrid (dense + BM25) indexing in Qdrant.

### Modules

- [x] `src/chunking/markdown_chunker.py`
  - [x] `MarkdownHeaderTextSplitter` primary split (`#`/`##`/`###`, `strip_headers=False`)
  - [x] `RecursiveCharacterTextSplitter` fallback for oversized sections (>1500 chars)
  - [x] Inject `header_path`, `doc_id`, `chunk_index`, `total_chunks`, `parser`, `pages` into metadata
- [x] `src/chunking/metadata.py` — content-hash `doc_id`, deterministic `chunk_uuid` (UUID5), ingestion timestamp
- [x] `src/indexing/embeddings.py` — dense (`text-embedding-3-small`, cached) + sparse (FastEmbed `Qdrant/bm25`)
- [x] `src/indexing/qdrant_store.py` — hybrid collection (named vectors + IDF modifier), upsert, doc-level dedup, library listing, delete-by-doc
- [x] Deduplication is part of `QdrantStore` (skip / replace / count-by-doc) — no separate module needed
- [x] `src/cache/embedding_cache.py` — wraps OpenAI embeddings with `CacheBackedEmbeddings` + `LocalFileStore`
- [x] `src/indexing/pipeline.py` — convert → chunk → upsert orchestrator

### Infrastructure

- [x] `docker-compose.yml` with Qdrant (REST 6333 + gRPC 6334)
- [x] `scripts/init_qdrant.py` — verifies/creates collection, supports `--recreate`

### Dependencies

- [x] Added `qdrant-client>=1.12`
- [x] Added `fastembed>=0.4.2`

### UI

- [x] Refactored `src/ui` into tab-based composition (`main_ui.py`)
- [x] New tab: **Ingest** — multi-file upload → convert → chunk → index, with library table, refresh, and delete-by-doc-id

**Acceptance:**
1. Upload doc → indexed with N chunks. ✅
2. Re-upload same doc → replaces by default (UUID5 deterministic IDs); checkbox flips to skip-if-exists. ✅
3. Qdrant has both dense + sparse vectors per chunk (named vectors). ✅
4. Each chunk has `header_path` metadata visible (e.g. `"Refund Policy > Eligibility"`). ✅

**Known limitation:** `py-rust-stemmers` 0.1.5 segfaults on Python 3.14
([qdrant/py-rust-stemmers#9](https://github.com/qdrant/py-rust-stemmers/pull/9)).
We pass `disable_stemmer=True` to FastEmbed BM25 as a workaround. Drop the
flag in `src/indexing/embeddings.py::build_sparse_embeddings` once a fixed
release is published. Quality impact is small (only stemming-sensitive
queries like "running"/"runs" are affected).

---

## Phase 4 — Hybrid Retrieval + Reranker + Basic Chat ✅

**Goal:** Ask questions, get answers grounded in indexed docs.

### Modules

- [x] `src/config/settings.py` — single source of truth for tunables (top-K, models, temperature, etc.) — overridable via `.env`
- [x] `src/retrieval/hybrid_search.py` — `HybridRetriever` (Qdrant `similarity_search_with_score` over the named-vector hybrid collection — server-side RRF fusion) + `RetrievalPipeline` (prefetch → rerank → trim) with `RetrievedChunk` + `RetrievalReport` dataclasses
- [x] `src/retrieval/reranker.py` — FlashRank ONNX cross-encoder wrapper (`ms-marco-MiniLM-L-12-v2` default, ~34 MB), graceful fallback if unavailable
- [x] Citations live next to retrieval (`RetrievedChunk.citation_label()`) — no dedicated `citations.py` module needed
- [x] `src/synthesis/response.py` — `GroundedAnswerer` builds a numbered-context prompt, calls `ChatOpenAI`, parses inline `[n]` citations into `Citation` objects
- [x] `src/ui/chat_ui.py` — Chatbot + textbox + sources panel + per-turn debug strip; lazy init for retrieval/reranker/LLM so the tab opens fast

### Refactor

- [x] Migrated existing modules (`indexing/embeddings.py`, `indexing/qdrant_store.py`, `chunking/markdown_chunker.py`, `core/qwen_parser.py`) to read defaults from `src.config.settings` instead of duplicated env reads / hardcoded constants
- [x] Reordered tabs (`Chat → Ingest → Convert`) so the primary workflow is front and center

### Dependencies

- [x] Added `flashrank>=0.2.9` (pure-ONNX reranker, no Torch — keeps Python 3.14 install clean)
- [x] LLM via existing `langchain-openai` (`ChatOpenAI`, model defaults to `gpt-4.1-mini`)

### UI

- [x] New tab: **Chat** — `gr.Chatbot` + submit textbox, sources accordion, per-turn debug line (model · prefetch / rerank timings)

**Acceptance:**
1. Query a document, get an answer with at least one citation. ✅
2. Citation links back to the source chunk + filename + header path. ✅
3. Configurable `RERANK_TOP_K` (default 5) and `RETRIEVAL_PREFETCH_K` (default 25) via `.env`. ✅
4. Reranker reorders the hybrid candidates (verified against the indexed sample corpus). ✅

### Deferred to Phase 6

- [ ] First Ragas baseline run (golden set + metrics) — moves with the other eval work in Phase 6 to keep this phase focused on the user-facing pipeline

---

## Phase 5 — Adaptive Query Router ⬜

**Goal:** Implement actual Adaptive RAG. Pick `no_retrieval | vector_only | sql_only | hybrid | clarify` per query.

- [ ] `src/routing/strategies.py` — strategy enum, dispatch table
- [ ] `src/routing/prompts.py` — router system prompt
- [ ] `src/routing/adaptive_router.py` — LLM classifier with structured output (Pydantic)
- [ ] `src/tools/sql_tool.py` — read-only SQL via function calling, with safety regex
- [ ] `src/tools/registry.py` — tool schemas for LLM
- [ ] Demo SQL dataset (synthetic e-commerce schema, seeded)

### Infrastructure

- [ ] Postgres in `docker-compose.yml` (or hook up Neon)
- [ ] Seed script for demo data

### Dependencies

- [ ] Add `sqlalchemy>=2.x`
- [ ] Add `psycopg[binary]>=3.x`

### Eval

- [ ] Expand golden set to 30-50 examples covering all 5 strategies
- [ ] Routing accuracy metric in CI

**Acceptance:**
1. "What's our refund policy?" → `vector_only`, returns policy.
2. "How many refunds last month?" → `sql_only`, returns count from DB.
3. "What's our refund policy and how many refunds last month?" → `hybrid`, both in synthesized answer.
4. "Hi" → `no_retrieval`, friendly response, no retrieval cost.
5. Routing accuracy >85% on golden set.

---

## Phase 6 — Evaluation, Tracing, Polish ⬜

**Goal:** Make this presentable as a portfolio piece.

- [ ] `src/eval/golden.jsonl` — finalized 30-50 Q&A pairs
- [ ] `src/eval/ragas_runner.py` — run all metrics, output HTML report
- [ ] `src/eval/reports/` — generated reports
- [ ] `src/observability/langfuse_client.py` — wrap LLM/embedding/retrieval calls
- [ ] `src/observability/cost_tracker.py` — $/query, $/ingest
- [ ] Cost dashboard tab in UI
- [ ] README rewrite — demo gif, screenshots, eval scores
- [ ] Architecture diagrams as images (mermaid → PNG)

### Dependencies

- [ ] Add `langfuse>=2.x`

**Acceptance:**
1. Eval report shows faithfulness/relevancy/precision/recall metrics.
2. Langfuse trace visible for every chat query.
3. Cost tracker shows per-query dollar cost.
4. README clearly explains what the project is and demonstrates it works.

---

## Phase 7 — Stretch Goals ⏸️

Optional, only if time permits.

- [ ] **C-RAG self-reflection** — grade retrieved context, fall back to web search if low relevance
- [ ] **Multi-hop retrieval** — when `clarify` strategy escalates to step-by-step search
- [ ] **MCP server surface** (`src/mcp_server/server.py`) — expose `search_docs` and `query_sql` tools to Cursor / Claude Desktop
- [ ] **Web search fallback** — Tavily / Exa when context insufficient
- [ ] **Streaming responses** — wire LLM streaming through Gradio
- [ ] **Multi-collection** — split per-domain (policies, finance, technical)
- [ ] **OCR of in-line images** — extract images from Docling output, OCR them, inline into markdown

---

## Currently Working On

**Phase 5 — Adaptive Query Router** ⬜

Next concrete action: design the router prompt + Pydantic strategy schema in `src/routing/`, plug it in front of `RetrievalPipeline`, and add a SQL tool.

---

## Quick Status

| Phase | Status | % |
|---|---|---|
| 0. Setup | ✅ | 100% |
| 1. Docling baseline | ✅ | 100% |
| 2. Parser router + Qwen | ✅ | 100% |
| 3. Chunking + indexing | ✅ | 100% |
| 4. Retrieval + chat | ✅ | 100% |
| 5. Adaptive router | ⬜ | 0% |
| 6. Eval + polish | ⬜ | 0% |
| 7. Stretch | ⏸️ | — |

Last updated: 2026-05-06
