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

## Phase 3 — Chunking + Indexing ⬜

**Goal:** Header-aware chunking + hybrid (dense + BM25) indexing in Qdrant.

### Modules

- [ ] `src/chunking/markdown_chunker.py`
  - [ ] `MarkdownHeaderTextSplitter` primary split
  - [ ] `RecursiveCharacterTextSplitter` fallback for oversized sections
  - [ ] Inject `header_path`, `doc_id`, `chunk_index`, `total_chunks`, `parser` into metadata
- [ ] `src/chunking/metadata.py` — content-hash doc_id, ingestion timestamp
- [ ] `src/indexing/embeddings.py` — dense (`text-embedding-3-small`) + sparse (FastEmbed BM25)
- [ ] `src/indexing/qdrant_store.py` — hybrid collection setup, upsert logic
- [ ] `src/indexing/deduplication.py` — skip already-indexed `doc_id`
- [ ] `src/cache/embedding_cache.py` — SHA256(text + model) → vector

### Infrastructure

- [ ] `docker-compose.yml` with Qdrant
- [ ] `scripts/init_qdrant.py` — create collection with hybrid config

### Dependencies

- [ ] Add `qdrant-client>=1.12`
- [ ] Add `fastembed>=0.4`

### UI

- [ ] New tab: "Ingest" — upload → convert → chunk → index → confirmation with chunk count

**Acceptance:**
1. Upload doc → indexed with N chunks.
2. Re-upload same doc → skipped (dedup by doc_id).
3. Qdrant has both dense + sparse vectors per chunk.
4. Each chunk has `header_path` metadata visible.

---

## Phase 4 — Hybrid Retrieval + Reranker + Basic Chat ⬜

**Goal:** Ask questions, get answers grounded in indexed docs.

- [ ] `src/retrieval/hybrid_search.py` — Qdrant prefetch (dense + sparse) with RRF fusion
- [ ] `src/retrieval/reranker.py` — BGE-reranker-v2-m3 (local) OR Cohere Rerank (API)
- [ ] `src/retrieval/citations.py` — chunk → source span mapping
- [ ] `src/synthesis/response.py` — combine reranked context + LLM, return answer + citations
- [ ] `src/ui/chat_ui.py` — chat interface with citation display
- [ ] First Ragas baseline run

### Dependencies

- [ ] Add `sentence-transformers>=3.0` (BGE reranker, local)
- [ ] Add `ragas>=0.2`, `datasets`

### UI

- [ ] New tab: "Chat" — query input, streaming answer, citation chips

**Acceptance:**
1. Query a document, get an answer with at least one citation.
2. Citation links back to the source chunk + filename.
3. Ragas faithfulness >0.80 on initial 20-question golden set.

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

**Phase 2 — Parser Router + Qwen3-VL OCR Fallback** 🚧

Next concrete action: refactor `src/core/` to split parsers, add Qwen, add caching, trim file_detector formats.

---

## Quick Status

| Phase | Status | % |
|---|---|---|
| 0. Setup | ✅ | 95% |
| 1. Docling baseline | ✅ | 100% |
| 2. Parser router + Qwen | 🚧 | 0% |
| 3. Chunking + indexing | ⬜ | 0% |
| 4. Retrieval + chat | ⬜ | 0% |
| 5. Adaptive router | ⬜ | 0% |
| 6. Eval + polish | ⬜ | 0% |
| 7. Stretch | ⏸️ | — |

Last updated: 2026-05-06
