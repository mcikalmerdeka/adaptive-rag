---
title: AdaptiveRAG
emoji: 🧠
colorFrom: blue
colorTo: purple
sdk: docker
app_file: app.py
pinned: false
license: mit
---

# AdaptiveRAG

**Hybrid Adaptive RAG with query-time strategy selection, markdown-first ingestion, and an optional MCP tool surface.**

This project intelligently routes data and queries: documents go to a hybrid (dense + sparse) vector store, structured data is queried live via tools, and the LLM picks the right strategy *per query* — not per file extension.

> Phased build. **Phase 6 complete** — Langfuse tracing wraps every router / retrieval / SQL / synthesis call, the Admin tab shows live token + cost rollups, and `src/eval/` has both a router-only accuracy gate and a DeepEval runner with HTML reports.

See:
- `ARCHITECTURE.md` — full system design and rationale
- `PROJECT_PLAN.md` — phase-by-phase checklist with progress

---

## What works today

### Phase 2 — Document → markdown
- **Multi-format input:** `.pdf`, `.docx`, `.pptx`, `.xlsx`, `.html` / `.htm`, `.md`, `.txt`, `.csv`, `.png`, `.jpg` / `.jpeg`, `.webp`, `.mp4`, `.mov`, `.mkv`
- **Smart parser routing:**

  | Input | Parser | Why |
  |---|---|---|
  | `.md`, `.txt` | passthrough | already markdown / plain text |
  | `.png`, `.jpg`, `.webp`, `.mp4`, `.mov`, `.mkv` | GLM-5.3-Flash | vision + video understanding beats local OCR |
  | `.pdf` (born-digital) | MarkItDown | fast, free, lossless text-layer extraction |
  | `.pdf` (scanned) | GLM-5.3-Flash per page | vision OCR beats text-layer on image pages |
  | `.docx`, `.pptx`, `.xlsx`, `.html`, `.csv` | MarkItDown | native structural parsing |

- **Video ingestion:** `.mp4`/`.mov`/`.mkv` (≤ GLM_VIDEO_MAX_UPLOAD_MB, base64 data URL) are analyzed by GLM-5.3-Flash into timestamped markdown (`## [mm:ss]` sections), so chat retrieval answers "what happens around minute 2?" with citations.
- **Born-digital vs scanned heuristic:** PDFs with <150 chars of extractable text in the first 3 pages route to GLM.
- **OCR cache:** SHA256-keyed `.cache/ocr/` so re-ingesting the same file is free.
- **GLM retry** with exponential backoff on rate limits / transient errors.

### Phase 3 — Header-aware chunking + hybrid Qdrant indexing
- **`MarkdownHeaderTextSplitter`** chunks on `#` / `##` / `###` and captures the path into metadata (e.g. `"Refund Policy > Eligibility"`). Sections >1500 chars are recursively split with 200-char overlap. Headers stay in the chunk content for richer embeddings.
- **Hybrid Qdrant collection:** named `dense` vector (1536-dim OpenAI `text-embedding-3-small`) + `sparse` vector (FastEmbed `Qdrant/bm25` with server-side IDF modifier).
- **Deterministic chunk IDs** via UUID5 of `(doc_id, chunk_index)` — re-ingest a doc and existing chunks get replaced cleanly, no duplicates.
- **Metadata per chunk:**

  ```python
  {
    "doc_id":       "a3f5b8c1d2e4f6a7",        # sha256(file_bytes)[:16]
    "source":       "/path/to/policy.pdf",
    "filename":     "policy.pdf",
    "extension":    ".pdf",
    "header_path":  "Refund Policy > Eligibility",
    "chunk_index":  7,
    "total_chunks": 23,
    "parser":       "markitdown",
    "pages":        24,
    "ingested_at":  "2026-05-06T03:50:00+00:00",
  }
  ```

- **Embedding cache** via a tiny SHA256-keyed disk cache — every (text, model) pair is cached on disk so re-embedding the same chunk is free.
- **Library view** in the UI — table of all indexed docs with a delete-by-doc-id action.
- **Two backends, zero config:** if `QDRANT_URL` is set we connect to a remote/Docker/Cloud Qdrant; otherwise we run embedded out of `./qdrant_storage/`.

### Phase 4 — Hybrid retrieval, reranker & grounded chat
- **Hybrid retrieval** via Qdrant's native server-side RRF fusion of the named `dense` (OpenAI) and `sparse` (BM25 IDF) vectors — single round-trip, no client-side fusion code.
- **Cross-encoder reranker** built on **FlashRank** (`ms-marco-MiniLM-L-12-v2`, ~34 MB ONNX, no PyTorch). Lazy first-use download; gracefully falls back to hybrid order if the model can't load.
- **Grounded answers** via `langchain-openai`'s `ChatOpenAI` with a strict system prompt that requires inline `[n]` citations and refuses to invent facts. The chat layer parses the cited indices and surfaces only those in the **Sources** panel.

### Phase 5 — Adaptive query router + read-only SQL tool
- **Five strategies, picked per query**:

  | Strategy | When | What runs |
  |---|---|---|
  | `no_retrieval` | greetings, generic knowledge, math | LLM only |
  | `vector_only` | "what does our doc say about X" | hybrid retrieve → rerank → LLM with `[n]` citations |
  | `sql_only` | "how many", "top N", aggregates | NL→SQL → read-only execute → LLM cites `[DB]` |
  | `hybrid` | both narrative AND a number | retrieve **and** SQL → blended answer |
  | `clarify` | genuinely ambiguous | one focused follow-up question, no retrieval cost |

- **Schema-aware classifier:** the router LLM (`gpt-6-luna` by default, at reasoning effort `none` — fast) sees a one-line summary of the available SQL tables when classifying. If `SQL_DATABASE_URL` is unset the router is told "no SQL backend", so it never picks a strategy it can't fulfill.

- **Read-only SQL tool with defense in depth:**
  1. Dedicated `adaptive_rag_ro` Postgres role (created by the seed script) with `SELECT`-only grants.
  2. Statement-level allowlist — only `SELECT` / `WITH` are accepted; multi-statements rejected.
  3. Forbidden-keyword regex catches anything that smells like a write or DDL even if the role grants would already block it.
  4. Per-session `statement_timeout` (default 5s) so runaway queries die fast.
  5. Implicit `LIMIT N` (default 200) appended if the SQL doesn't already cap rows.

- **Demo dataset:** `scripts/seed_demo_data.py` writes a deterministic e-commerce schema (customers, products, orders, order_items, refunds) so the SQL strategies have something real to query out of the box.

- **All knobs in one place:** `src/config/settings.py` is the single source of truth. Override via `.env`:
  - `RERANK_TOP_K=5` (final chunks shown to the LLM, default `5`)
  - `RETRIEVAL_PREFETCH_K=25` (candidates fetched before reranking)
  - `RERANKER_MODEL` (swap to `ms-marco-TinyBERT-L-2-v2` for speed or `rank-T5-flan` for quality)
  - `LLM_MODEL`, `LLM_TEMPERATURE`, `LLM_MAX_TOKENS`, `LLM_REASONING_EFFORT` (synthesis — default `gpt-6-luna` at effort `high`)
  - `ROUTER_MODEL`, `ROUTER_TEMPERATURE`, `ROUTER_REASONING_EFFORT` (classifier — default `gpt-6-luna` at effort `none`)
  - `SQL_MODEL`, `SQL_REASONING_EFFORT` (NL→SQL translator — default `gpt-6-luna` at effort `high`)
  - `SQL_DATABASE_URL`, `SQL_QUERY_TIMEOUT_SEC`, `SQL_ROW_LIMIT` (Phase 5)
  - `DENSE_MODEL`, `SPARSE_MODEL`, `CHUNK_SIZE`, `CHUNK_OVERLAP`, etc.

### Phase 6 — Tracing, evaluation, cost tracking
- **Langfuse tracing** for every chat turn — one parent `chat.turn` span with child spans `router.classify`, `retrieval.hybrid_search`, `tool.sql_execute`, `synthesis.{direct,grounded}`. The `langchain.CallbackHandler` is also passed into every `ChatOpenAI.invoke(...)`, so token counts and USD costs land in Langfuse automatically. Tracing is **completely no-op when `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` are unset** — the spans are stubs and the rest of the code is unchanged.
- **Admin tab** in the Gradio app — live cost / token / trace counts pulled from Langfuse's `/api/public/metrics/daily` endpoint. Selectable window (last 24 h / 7 d / 30 d), per-model breakdown, per-day breakdown. Friendly empty-state when keys aren't configured.
- **Router-only golden eval** (`uv run python -m src.eval.run_routing_eval`) — runs the router against `src/eval/golden.jsonl` (a **small smoke set**, one example per strategy, to save tokens). Writes `src/eval/reports/routing.json`. Add `--threshold 0.85` if you want a non-zero exit on regressions (default: never fail — report only).
- **DeepEval eval** (`uv run python -m src.eval.run_deepeval`) — runs the full dispatcher on the retrieval-bearing examples and scores them with `Faithfulness`, `AnswerRelevancy`, `ContextualRelevancy`. Emits both a JSON dump and a self-contained HTML report under `src/eval/reports/deepeval_<timestamp>.html`.

## Project structure

```
adaptive-rag/
├── app.py                          # Gradio entry
├── ARCHITECTURE.md
├── PROJECT_PLAN.md
├── docker-compose.yml              # Qdrant service
├── .env.example
├── pyproject.toml
├── requirements.txt
├── scripts/
│   └── init_qdrant.py              # Bootstrap or recreate the collection
└── src/
    ├── config/                     # Single source of truth for all tunables
    │   └── settings.py             # reads .env once, exposes immutable Settings
    ├── core/                       # Document → markdown
    │   ├── file_detector.py
    │   ├── markitdown_parser.py      MarkItDown plain conversions (PDF/office/html/csv)
    │   ├── office_renderer.py        Office COM / LibreOffice → PDF for rendered mode
    │   ├── glm_parser.py             GLM-5.3-Flash OCR + video via Z.ai
    │   ├── parser_router.py          auto/plain/rendered mode dispatch
    │   └── converter.py
    ├── chunking/                   # Markdown → header-aware chunks
    │   ├── markdown_chunker.py
    │   └── metadata.py             # doc_id, chunk_uuid, base metadata
    ├── indexing/                   # Chunks → Qdrant
    │   ├── embeddings.py           # dense (cached) + sparse (BM25)
    │   ├── qdrant_store.py         # hybrid collection + dedup + library
    │   └── pipeline.py             # convert → chunk → upsert
    ├── retrieval/                  # Query → ranked chunks
    │   ├── hybrid_search.py        # HybridRetriever + RetrievalPipeline
    │   └── reranker.py             # FlashRank ONNX cross-encoder wrapper
    ├── routing/                    # Adaptive query router + dispatcher
    │   ├── strategies.py           # Strategy StrEnum + capability sets
    │   ├── prompts.py              # router system prompt + few-shots
    │   ├── adaptive_router.py      # LLM classifier (structured output)
    │   └── dispatcher.py           # AdaptiveDispatcher: route → run → synth
    ├── tools/                      # External tools the router can dispatch to
    │   └── sql_tool.py             # NL→SQL with read-only safety guards
    ├── synthesis/                  # Chunks (+ SQL) → grounded answer + citations
    │   └── response.py             # GroundedAnswerer (ChatOpenAI)
    ├── observability/              # Tracing + cost tracking (Langfuse)
    │   ├── langfuse_client.py      # Singleton + no-op span() context manager
    │   └── cost_tracker.py         # Pulls daily metrics from Langfuse REST API
    ├── eval/                       # Golden set + accuracy / DeepEval runners
    │   ├── golden.jsonl            # Tiny smoke golden set (~10 rows; extend as needed)
    │   ├── run_routing_eval.py     # Router-only accuracy gate
    │   └── run_deepeval.py         # Faithfulness / relevancy / contextual relevancy + HTML
    ├── cache/
    │   ├── ocr_cache.py            # SHA256 disk cache for OCR markdown
    │   └── embedding_cache.py      # SHA256 disk cache for embeddings
    ├── utils/
    │   └── pdf_inspector.py        # born-digital heuristic + page rendering
    └── ui/
        ├── main_ui.py              # Tab composition
        ├── chat_ui.py              # Chat tab (talks to AdaptiveDispatcher)
        ├── ingest_ui.py            # Ingest tab
        ├── markdown_converter_ui.py # Convert tab
        └── admin_ui.py             # Admin tab — Langfuse cost dashboard
```

## Setup

```bash
# 1. Install dependencies (uv recommended)
uv sync

# 2. Copy and fill in your API keys
cp .env.example .env
# edit .env and set OPENAI_API_KEY and ZAI_API_KEY

# 3. (Optional) Start Qdrant in Docker — only if you don't want embedded mode
docker compose up -d qdrant
# then in .env: QDRANT_URL=http://localhost:6333

# 4. (Optional) Start Postgres + seed demo e-commerce data so the
#    sql_only / hybrid strategies have something to query.
docker compose up -d postgres
uv run python scripts/seed_demo_data.py
# then in .env:
#   SQL_DATABASE_URL=postgresql+psycopg://adaptive_rag_ro:adaptive_rag_ro@localhost:5433/adaptive_rag

# 5. Run the app
uv run app.py
```

Open `http://localhost:7860`.

> First run downloads the FastEmbed BM25 tokenizer (~few MB) and (on first chat turn) the FlashRank reranker (~34 MB). MarkItDown downloads nothing.
>
> The bundled Postgres binds to **host port 5433** (not 5432) to avoid colliding with a host-installed Postgres. If you want to use Neon / RDS / your own Postgres, just point `SQL_DATABASE_URL` at it (the connection only needs `SELECT` rights on the target tables). Leave `SQL_DATABASE_URL` unset to disable the SQL strategies entirely — the router will never pick them in that case.

## API keys

| Variable | Used for | Get it at |
|---|---|---|
| `OPENAI_API_KEY` | Dense embeddings + chat LLM + router + NL→SQL | https://platform.openai.com/ |
| `ZAI_API_KEY` | Image + scanned-PDF OCR + video analysis via GLM-5.3-Flash | https://z.ai/manage-apikey/apikey-list |
| `ZAI_BASE_URL` (optional, default `https://api.z.ai/api/paas/v4/`) | Z.ai PAAS v4 endpoint (OpenAI-compatible) | — |
| `GLM_MODEL` (optional, default `glm-5.3-flash`) | Vision+video model used for OCR (or `glm-5.3-flashx` for ~200 tok/s) | — |
| `GLM_REASONING_EFFORT` (optional, default `low`) | Thinking depth for ingestion calls (`low`/`high`/`max`) | — |
| `GLM_MAX_TOKENS` (optional, default `8192`) | Output budget per GLM call (video transcripts need headroom) | — |
| `GLM_VIDEO_MAX_UPLOAD_MB` (optional, default `20`) | Base64 video size guard (Z.ai's 200 MB cap applies to URL mode) | — |
| `QDRANT_URL` (optional) | Connect to a remote Qdrant. Leave unset for embedded mode. | — |
| `QDRANT_API_KEY` (optional) | Qdrant Cloud auth | https://cloud.qdrant.io/ |
| `QDRANT_PATH` (optional) | Override the embedded storage directory | — |
| `QDRANT_COLLECTION` (optional) | Override the default collection name (`adaptive_rag`) | — |
| `SQL_DATABASE_URL` (optional) | SQLAlchemy URL for the SQL tool. Leave unset to disable `sql_only` / `hybrid` strategies. | — |
| `SQL_QUERY_TIMEOUT_SEC` (optional, default `5`) | Per-query Postgres `statement_timeout` | — |
| `SQL_ROW_LIMIT` (optional, default `200`) | Implicit `LIMIT N` injected when the SQL doesn't have one | — |
| `LLM_MODEL` (optional, default `gpt-6-luna`) | Synthesis LLM; reasoning effort set via `LLM_REASONING_EFFORT` (`high` by default) | — |
| `ROUTER_MODEL` (optional, default `gpt-6-luna`) | Router classifier model (`ROUTER_REASONING_EFFORT=none` by default) | — |
| `SQL_MODEL` (optional, default `gpt-6-luna`) | NL→SQL translator model (`SQL_REASONING_EFFORT=high` by default) | — |
| `LANGFUSE_PUBLIC_KEY` (optional) | Langfuse tracing — set both to enable. App is a no-op tracer when missing. | https://cloud.langfuse.com/ |
| `LANGFUSE_SECRET_KEY` (optional) | Same as above | — |
| `LANGFUSE_HOST` (optional, default `https://cloud.langfuse.com`) | Set to `https://us.cloud.langfuse.com` for the US region or your self-hosted URL | — |

## Using the app

**Chat tab** — ask questions about your indexed documents *and* the SQL warehouse. Each turn runs the **adaptive router** first to pick a strategy, then dispatches: vector queries hit Qdrant (dense + BM25 + RRF + cross-encoder rerank, top `RERANK_TOP_K` chunks); SQL queries hit Postgres read-only with safety guards. Inline `[n]` citations resolve to chunks, `[DB]` to the executed query. The **Sources** panel on the right shows the router's decision + reasoning, the executed SQL with its first 5 rows, and the cited chunks with rerank scores. The footer line shows per-stage timings (routing / retrieval / sql / synthesis / total).

**Ingest tab** — multi-file ingestion. Each file is converted → chunked → upserted into Qdrant. The library on the right shows what's currently indexed and lets you delete by `doc_id`. Re-ingesting a file by default replaces its previous chunks; tick **Skip if already indexed** to no-op instead.

**Convert tab** — single-document preview; pick a file, optionally force GLM for PDFs, see the markdown and download.

**Admin tab** — token + USD cost rollups pulled from Langfuse. Disabled-state instructions when `LANGFUSE_*` keys are missing.

## Evaluation

```bash
# Router-only accuracy (cheap, ~10 LLM calls). Exits non-zero if accuracy
# drops below 85% — drop this into CI to catch prompt regressions.
uv run python -m src.eval.run_routing_eval

# Full pipeline through DeepEval (faithfulness / answer relevancy /
# contextual relevancy). Generates JSON + a self-contained HTML report
# under src/eval/reports/.
uv run python -m src.eval.run_deepeval
uv run python -m src.eval.run_deepeval --limit 1  # cheapest: one row only

# Quick cost snapshot from the CLI (or use the Admin tab).
uv run python -m src.observability.cost_tracker --days 7
```

## Roadmap

- ✅ Phase 1: Baseline document conversion (v1 parser, superseded by MarkItDown)
- ✅ Phase 2: Parser router (plain MarkItDown + GLM-5.3-Flash rendered/OCR) with caching + video ingestion
- ✅ Phase 3: Header-aware chunking + hybrid (dense + BM25) Qdrant indexing
- ✅ Phase 4: Hybrid retrieval + FlashRank reranker + grounded chat with citations
- ✅ Phase 5: Adaptive query router + read-only SQL tool over a demo Postgres warehouse
- ✅ Phase 6: Langfuse tracing + cost dashboard + routing eval + DeepEval runner
- ⏸️ Phase 7: C-RAG self-reflection, MCP server surface, web fallback, streaming

Full plan in `PROJECT_PLAN.md`.

## License

MIT
