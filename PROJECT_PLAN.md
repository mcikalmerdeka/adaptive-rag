# AdaptiveRAG — Project Plan & Progress Tracker

> Master checklist for the entire build. Update status markers as work completes. See `ARCHITECTURE.md` for design rationale.

**Status legend:** ✅ done · 🚧 in progress · ⬜ pending · ⏸️ deferred · ❌ cancelled

---

## Phase 0 — Project Setup ✅

- Repo initialized (`.git`, `.gitignore`, `.gitattributes`)
- Python 3.14 + `uv` package manager
- `pyproject.toml` with core deps
- `.env` for API keys (`OPENAI_API_KEY`, `QWEN_API_KEY`)
- `AGENTS.md` engineering principles
- `ARCHITECTURE.md` system design
- `PROJECT_PLAN.md` (this file)
- `.env.example` template

---

## Phase 1 — Document → Markdown (Docling baseline) ✅

**Goal:** Upload a document, get clean markdown back. Docling-only.

- `src/core/file_detector.py` — extension/MIME detection
- `src/core/converter.py` — Docling wrapper
- `src/ui/markdown_converter_ui.py` — Gradio upload/preview/download UI
- `app.py` — entry point
- Docling model warm-up on startup

**Acceptance:** Upload PDF/DOCX/PPTX, see markdown rendered, download `.md` file.

---

## Phase 2 — Parser Router + Qwen3-VL OCR Fallback 🚧

**Goal:** Route per-file-type. Use Docling for digital formats, Qwen3-VL for images and scanned PDFs. Add caching so iteration doesn't burn API credits.

### Cleanup

- Trim `file_detector.py` to common formats only (drop ASCIIDOC, LaTeX, XML, JSON, audio/video, VTT, BMP, TIFF, format variants like `.dotx`/`.docm`/etc.)

### New modules

- `src/utils/pdf_inspector.py`
  - `is_scanned_pdf(path) -> bool` heuristic (sample first 3 pages, threshold by extracted text length)
  - `render_pdf_pages(path, dpi=150) -> Iterator[bytes]` (PNG bytes via `pypdfium2`)
- `src/cache/ocr_cache.py` — SHA256-keyed disk cache for OCR results
- `src/core/qwen_parser.py`
  - `QwenParser.extract_image(path) -> str`
  - `QwenParser.extract_pdf_pages(path) -> str` (per-page caching, concat)
  - Tenacity retry on rate limits / network errors
  - Deterministic OCR prompt
- `src/core/docling_parser.py` — Docling-only parser (extracted from `converter.py`)
- `src/core/parser_router.py` — dispatches:
  ```
  .md / .txt           → passthrough (read file)
  .png / .jpg / .webp  → Qwen
  .pdf scanned         → Qwen (per page, cached)
  .pdf born-digital    → Docling
  .docx / .pptx / .xlsx / .html / .csv → Docling
  ```

### Refactor

- `src/core/converter.py` — slim down to public API, delegate to `parser_router`
- `src/core/__init__.py` — update exports

### UI

- Toggle: "Force Qwen3-VL OCR for PDFs" (override born-digital heuristic)
- Progress indicator for multi-page scanned PDFs
- Show parser used (`docling` / `qwen3-vl` / `passthrough`) in status

### Dependencies

- Add `pypdfium2>=4.30` (PDF inspection + rendering)
- Add `tenacity>=9.0` (retry)
- Add `pillow>=10` (PIL image handling — also Docling transitive but pin explicit)

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

- `src/chunking/markdown_chunker.py`
  - `MarkdownHeaderTextSplitter` primary split (`#`/`##`/`###`, `strip_headers=False`)
  - `RecursiveCharacterTextSplitter` fallback for oversized sections (>1500 chars)
  - Inject `header_path`, `doc_id`, `chunk_index`, `total_chunks`, `parser`, `pages` into metadata
- `src/chunking/metadata.py` — content-hash `doc_id`, deterministic `chunk_uuid` (UUID5), ingestion timestamp
- `src/indexing/embeddings.py` — dense (`text-embedding-3-small`, cached) + sparse (FastEmbed `Qdrant/bm25`)
- `src/indexing/qdrant_store.py` — hybrid collection (named vectors + IDF modifier), upsert, doc-level dedup, library listing, delete-by-doc
- Deduplication is part of `QdrantStore` (skip / replace / count-by-doc) — no separate module needed
- `src/cache/embedding_cache.py` — wraps OpenAI embeddings with `CacheBackedEmbeddings` + `LocalFileStore`
- `src/indexing/pipeline.py` — convert → chunk → upsert orchestrator

### Infrastructure

- `docker-compose.yml` with Qdrant (REST 6333 + gRPC 6334)
- `scripts/init_qdrant.py` — verifies/creates collection, supports `--recreate`

### Dependencies

- Added `qdrant-client>=1.12`
- Added `fastembed>=0.4.2`

### UI

- Refactored `src/ui` into tab-based composition (`main_ui.py`)
- New tab: **Ingest** — multi-file upload → convert → chunk → index, with library table, refresh, and delete-by-doc-id

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

- `src/config/settings.py` — single source of truth for tunables (top-K, models, temperature, etc.) — overridable via `.env`
- `src/retrieval/hybrid_search.py` — `HybridRetriever` (Qdrant `similarity_search_with_score` over the named-vector hybrid collection — server-side RRF fusion) + `RetrievalPipeline` (prefetch → rerank → trim) with `RetrievedChunk` + `RetrievalReport` dataclasses
- `src/retrieval/reranker.py` — FlashRank ONNX cross-encoder wrapper (`ms-marco-MiniLM-L-12-v2` default, ~34 MB), graceful fallback if unavailable
- Citations live next to retrieval (`RetrievedChunk.citation_label()`) — no dedicated `citations.py` module needed
- `src/synthesis/response.py` — `GroundedAnswerer` builds a numbered-context prompt, calls `ChatOpenAI`, parses inline `[n]` citations into `Citation` objects
- `src/ui/chat_ui.py` — Chatbot + textbox + sources panel + per-turn debug strip; lazy init for retrieval/reranker/LLM so the tab opens fast

### Refactor

- Migrated existing modules (`indexing/embeddings.py`, `indexing/qdrant_store.py`, `chunking/markdown_chunker.py`, `core/qwen_parser.py`) to read defaults from `src.config.settings` instead of duplicated env reads / hardcoded constants
- Reordered tabs (`Chat → Ingest → Convert`) so the primary workflow is front and center

### Dependencies

- Added `flashrank>=0.2.9` (pure-ONNX reranker, no Torch — keeps Python 3.14 install clean)
- LLM via existing `langchain-openai` (`ChatOpenAI`, model defaults to `gpt-4.1-mini`)

### UI

- New tab: **Chat** — `gr.Chatbot` + submit textbox, sources accordion, per-turn debug line (model · prefetch / rerank timings)

**Acceptance:**

1. Query a document, get an answer with at least one citation. ✅
2. Citation links back to the source chunk + filename + header path. ✅
3. Configurable `RERANK_TOP_K` (default 5) and `RETRIEVAL_PREFETCH_K` (default 25) via `.env`. ✅
4. Reranker reorders the hybrid candidates (verified against the indexed sample corpus). ✅

### Deferred to Phase 6

- First Ragas baseline run (golden set + metrics) — moves with the other eval work in Phase 6 to keep this phase focused on the user-facing pipeline

---

## Phase 5 — Adaptive Query Router ✅

**Goal:** Implement actual Adaptive RAG. Pick `no_retrieval | vector_only | sql_only | hybrid | clarify` per query.

### Routing layer

- `src/routing/strategies.py` — `Strategy` `StrEnum` + label / capability sets
- `src/routing/prompts.py` — router system prompt + few-shot examples + schema injection
- `src/routing/adaptive_router.py` — `ChatOpenAI(...).with_structured_output(RouterDecision)` classifier; passes chat history; sanitizes (downgrades SQL strategies if backend missing, fills missing clarify question)
- `src/routing/dispatcher.py` — `AdaptiveDispatcher` orchestrates router → retrieval → SQL → synthesis with per-stage timings, lazy backends, and graceful SQL fallback

### Tools

- `src/tools/sql_tool.py` — schema introspection, NL→SQL via `with_structured_output(_SqlOutput)`, statement-level allowlist (only `SELECT`/`WITH`), forbidden-keyword regex, no-multi-statement guard, server-side `statement_timeout`, transaction-level `READ ONLY`, automatic `LIMIT N` injection
- `src/tools/registry.py` — **dropped on purpose.** With explicit routing → dispatch we don't need a function-calling registry abstraction; `SqlTool` is just a class. Documented in code comments / decision log.

### Synthesis

- Extended `GroundedAnswerer` with `answer_direct(...)` (no_retrieval) and `answer_with_sql(...)` (sql_only / hybrid). Single citation model: `[1]..[N]` for chunks, `[DB]` for SQL — parsed back out into `AnswerResponse.cited_indices` / `cited_db`.

### Demo data

- `scripts/seed_demo_data.py` — deterministic e-commerce dataset (100 customers, 50 products, 500 orders, ~1300 line items, ~35 refunds). Idempotent (skips if already populated) with `--recreate` flag. Creates a dedicated read-only role `adaptive_rag_ro` with `SELECT`-only grants for the app to use.

### Infrastructure

- Postgres added to `docker-compose.yml` (`postgres:17-alpine`, healthcheck, persistent volume). **Bound to host port `5433`** (not `5432`) to dodge collisions with a host-installed Postgres.
- `.env.example` documents `SQL_DATABASE_URL`, `SQL_QUERY_TIMEOUT_SEC`, `SQL_ROW_LIMIT`, `ROUTER_MODEL`, `ROUTER_TEMPERATURE`, `SQL_MODEL`. All wired through `src.config.settings`.

### Dependencies

- Added `sqlalchemy>=2.0.36`
- Added `psycopg[binary]>=3.2.3`
- Added explicit `pydantic>=2.9.0` (already a transitive dep, pinned for clarity)

### UI

- Refactored `src/ui/chat_ui.py` to call `AdaptiveDispatcher`. Sources panel now shows: strategy badge + reasoning, executed SQL with first 5 result rows, and chunk citations. Per-turn debug strip shows per-stage timings.

**Acceptance:**

1. ✅ "What does the indexed story say about the aliens arriving in Jakarta?" → `vector_only` (5 chunks retrieved, 5 cited, narrative answer).
2. ✅ "How many refunds last 30 days?" → `sql_only` (`SELECT COUNT(*) FROM refunds WHERE created_at >= NOW() - INTERVAL '30 days'` → "3 refunds [DB]").
3. ✅ "Summarize the indexed story and tell me total refunds in our database" → `hybrid` (chunks + SQL, blended answer).
4. ✅ "Hi there!" → `no_retrieval`.
5. ✅ "What about last quarter?" → `clarify` ("Could you specify what information about last quarter you're interested in — sales, refunds, new customers?").

### Deferred to Phase 6

- Routing accuracy metric on a golden set (30-50 examples) — moves with the rest of the eval work.
- Top-N products SQL with `ORDER BY ... DESC` is correct, but synthesis truncates the list when the chunk slice cuts mid-list. Worth a small system-prompt tweak in Phase 6.

### Known surprises (from smoke test)

- The router will pick `no_retrieval` over `vector_only` for vague conversational openers like "What happens in the story?" without prior turns — it asks "which story?" instead of blindly searching. Defensible behavior; document the workaround (be specific, e.g. "What does the indexed story say about X").

---

## Phase 6 — Evaluation, Tracing, Polish ✅

**Goal:** Make this presentable as a portfolio piece.

### Observability (Langfuse)

- `src/observability/langfuse_client.py` — lazy singleton `Langfuse` client, no-op `span()` context manager when keys are missing, `CallbackHandler` factory for LangChain
- `src/observability/cost_tracker.py` — read-side helper that pulls daily metrics from Langfuse's `/api/public/metrics/daily` endpoint (no separate price table to maintain)
- `src/routing/dispatcher.py` — wraps every chat turn in a parent `chat.turn` span with child spans `router.classify`, `retrieval.hybrid_search`, `tool.sql_execute`, `synthesis.direct` / `synthesis.grounded`. Auto-flushes after each turn so traces appear immediately even in short-lived Gradio request cycles.
- `src/routing/adaptive_router.py`, `src/synthesis/response.py`, `src/tools/sql_tool.py` — every `ChatOpenAI.invoke(...)` call now passes `config={"callbacks": get_callback_handler(), "run_name": "...", "metadata": {...}}` so token usage + cost get captured automatically.

### Evaluation

- `src/eval/golden.jsonl` — **minimal smoke set** (≈5 rows, one per strategy) to avoid burning tokens; extend the file anytime you want stronger coverage.
- `src/eval/run_routing_eval.py` — router-only accuracy + breakdown; **`--threshold` is opt-in** (default: print report only) so tiny goldens don’t spam failures
- `src/eval/run_ragas.py` — runs the full dispatcher on retrieval-bearing examples and scores them with `Faithfulness`, `ResponseRelevancy`, `LLMContextPrecisionWithoutReference`. Emits both a JSON dump and a self-contained HTML report under `src/eval/reports/`.
- `src/eval/__init__.py` + `src/eval/reports/` (gitignored)

### UI

- New tab: **Admin** — Langfuse cost / usage dashboard with selectable window (24h / 7d / 30d), per-model breakdown, per-day breakdown. Friendly empty-state when keys aren't configured.

### Dependencies

- `langfuse>=4.0.0`
- `ragas>=0.2.10`
- `datasets>=3.0.0` (Ragas dependency, pinned for clarity)

### Configuration

- `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST` added to `.env`, `.env.example`, and `src/config/settings.py`. `Settings.langfuse_enabled` returns `True` only when both keys are set.

**Acceptance:**

1. ✅ Routing eval prints per-strategy accuracy and writes `src/eval/reports/routing.json`. Pass `--threshold 0.85` in CI when you want a hard gate.
2. ✅ Ragas eval emits faithfulness / response relevancy / context precision in both JSON and HTML.
3. ✅ Every chat turn produces a Langfuse trace with router / retrieval / SQL / synthesis spans (when keys are set; otherwise the app behaves identically and the spans are no-ops).
4. ✅ Admin tab renders cost + token totals (and a friendly setup message when Langfuse is disabled).

---

## Phase 7 — Stretch Goals ⏸️

Optional, only if time permits.

- **C-RAG self-reflection** — grade retrieved context, fall back to web search if low relevance
- **Multi-hop retrieval** — when `clarify` strategy escalates to step-by-step search
- **MCP server surface** (`src/mcp_server/server.py`) — expose `search_docs` and `query_sql` tools to Cursor / Claude Desktop
- **Web search fallback** — Tavily / Exa when context insufficient
- **Streaming responses** — wire LLM streaming through Gradio
- **Multi-collection** — split per-domain (policies, finance, technical)
- **OCR of in-line images** — extract images from Docling output, OCR them, inline into markdown

---

## Currently Working On

**Phase 7 — Stretch Goals** ⏸️

Phase 6 is complete. Pick whichever stretch goal is most valuable next: streaming responses through Gradio, MCP server surface for Cursor / Claude Desktop, or C-RAG self-reflection with web search fallback.

---

## Quick Status


| Phase                   | Status | %    |
| ----------------------- | ------ | ---- |
| 0. Setup                | ✅      | 100% |
| 1. Docling baseline     | ✅      | 100% |
| 2. Parser router + Qwen | ✅      | 100% |
| 3. Chunking + indexing  | ✅      | 100% |
| 4. Retrieval + chat     | ✅      | 100% |
| 5. Adaptive router      | ✅      | 100% |
| 6. Eval + polish        | ✅      | 100% |
| 7. Stretch              | ⏸️     | —    |


Last updated: 2026-05-10