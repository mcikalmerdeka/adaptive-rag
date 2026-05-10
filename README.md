# AdaptiveRAG

**Hybrid Adaptive RAG with query-time strategy selection, markdown-first ingestion, and an optional MCP tool surface.**

This project intelligently routes data and queries: documents go to a hybrid (dense + sparse) vector store, structured data is queried live via tools, and the LLM picks the right strategy *per query* — not per file extension.

> Phased build. **Phase 6 complete** — Langfuse tracing wraps every router / retrieval / SQL / synthesis call, the Admin tab shows live token + cost rollups, and `src/eval/` has both a router-only accuracy gate and a Ragas runner with HTML reports.

See:
- `ARCHITECTURE.md` — full system design and rationale
- `PROJECT_PLAN.md` — phase-by-phase checklist with progress

---

## What works today

### Phase 2 — Document → markdown
- **Multi-format input:** `.pdf`, `.docx`, `.pptx`, `.xlsx`, `.html` / `.htm`, `.md`, `.txt`, `.csv`, `.png`, `.jpg` / `.jpeg`, `.webp`
- **Smart parser routing:**

  | Input | Parser | Why |
  |---|---|---|
  | `.md`, `.txt` | passthrough | already markdown / plain text |
  | `.png`, `.jpg`, `.webp` | Qwen3-VL | vision model beats local OCR |
  | `.pdf` (born-digital) | Docling | fast, free, lossless |
  | `.pdf` (scanned) | Qwen3-VL per page | better than EasyOCR on layouts |
  | `.docx`, `.pptx`, `.xlsx`, `.html`, `.csv` | Docling | native structural parsing |

- **Born-digital vs scanned heuristic:** PDFs with <150 chars of extractable text in the first 3 pages route to Qwen.
- **OCR cache:** SHA256-keyed `.cache/ocr/` so re-ingesting the same file is free.
- **Qwen retry** with exponential backoff on rate limits / transient errors.

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
    "parser":       "docling",
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

- **Schema-aware classifier:** the router LLM (`gpt-4.1-nano` by default — cheap, fast) sees a one-line summary of the available SQL tables when classifying. If `SQL_DATABASE_URL` is unset the router is told "no SQL backend", so it never picks a strategy it can't fulfill.

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
  - `LLM_MODEL`, `LLM_TEMPERATURE`, `LLM_MAX_TOKENS` (synthesis)
  - `ROUTER_MODEL`, `ROUTER_TEMPERATURE` (classifier)
  - `SQL_MODEL` (NL→SQL translator)
  - `SQL_DATABASE_URL`, `SQL_QUERY_TIMEOUT_SEC`, `SQL_ROW_LIMIT` (Phase 5)
  - `DENSE_MODEL`, `SPARSE_MODEL`, `CHUNK_SIZE`, `CHUNK_OVERLAP`, etc.

### Phase 6 — Tracing, evaluation, cost tracking
- **Langfuse tracing** for every chat turn — one parent `chat.turn` span with child spans `router.classify`, `retrieval.hybrid_search`, `tool.sql_execute`, `synthesis.{direct,grounded}`. The `langchain.CallbackHandler` is also passed into every `ChatOpenAI.invoke(...)`, so token counts and USD costs land in Langfuse automatically. Tracing is **completely no-op when `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` are unset** — the spans are stubs and the rest of the code is unchanged.
- **Admin tab** in the Gradio app — live cost / token / trace counts pulled from Langfuse's `/api/public/metrics/daily` endpoint. Selectable window (last 24 h / 7 d / 30 d), per-model breakdown, per-day breakdown. Friendly empty-state when keys aren't configured.
- **Router-only golden eval** (`uv run python -m src.eval.run_routing_eval`) — runs the router against `src/eval/golden.jsonl` (a **small smoke set**, one example per strategy, to save tokens). Writes `src/eval/reports/routing.json`. Add `--threshold 0.85` if you want a non-zero exit on regressions (default: never fail — report only).
- **Ragas eval** (`uv run python -m src.eval.run_ragas`) — runs the full dispatcher on the retrieval-bearing examples and scores them with `Faithfulness`, `ResponseRelevancy`, `LLMContextPrecisionWithoutReference`. Emits both a JSON dump and a self-contained HTML report under `src/eval/reports/ragas_<timestamp>.html`.

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
    │   ├── docling_parser.py
    │   ├── qwen_parser.py
    │   ├── parser_router.py
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
    ├── eval/                       # Golden set + accuracy / Ragas runners
    │   ├── golden.jsonl            # Tiny smoke golden set (~5 rows; extend as needed)
    │   ├── run_routing_eval.py     # Router-only accuracy gate
    │   └── run_ragas.py            # Faithfulness / relevancy / precision + HTML
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
# edit .env and set OPENAI_API_KEY and QWEN_API_KEY

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

> First run downloads Docling (~1-2 GB), the FastEmbed BM25 tokenizer (~few MB), and (on first chat turn) the FlashRank reranker (~34 MB).
>
> The bundled Postgres binds to **host port 5433** (not 5432) to avoid colliding with a host-installed Postgres. If you want to use Neon / RDS / your own Postgres, just point `SQL_DATABASE_URL` at it (the connection only needs `SELECT` rights on the target tables). Leave `SQL_DATABASE_URL` unset to disable the SQL strategies entirely — the router will never pick them in that case.

## API keys

| Variable | Used for | Get it at |
|---|---|---|
| `OPENAI_API_KEY` | Dense embeddings + chat LLM + router + NL→SQL | https://platform.openai.com/ |
| `QWEN_API_KEY` | Image + scanned PDF OCR via Qwen3-VL | https://dashscope.aliyun.com/ |
| `QDRANT_URL` (optional) | Connect to a remote Qdrant. Leave unset for embedded mode. | — |
| `QDRANT_API_KEY` (optional) | Qdrant Cloud auth | https://cloud.qdrant.io/ |
| `QDRANT_PATH` (optional) | Override the embedded storage directory | — |
| `QDRANT_COLLECTION` (optional) | Override the default collection name (`adaptive_rag`) | — |
| `SQL_DATABASE_URL` (optional) | SQLAlchemy URL for the SQL tool. Leave unset to disable `sql_only` / `hybrid` strategies. | — |
| `SQL_QUERY_TIMEOUT_SEC` (optional, default `5`) | Per-query Postgres `statement_timeout` | — |
| `SQL_ROW_LIMIT` (optional, default `200`) | Implicit `LIMIT N` injected when the SQL doesn't have one | — |
| `ROUTER_MODEL` (optional, default `gpt-4.1-nano`) | Router classifier model | — |
| `SQL_MODEL` (optional, default `gpt-4.1-mini`) | NL→SQL translator model | — |
| `LANGFUSE_PUBLIC_KEY` (optional) | Langfuse tracing — set both to enable. App is a no-op tracer when missing. | https://cloud.langfuse.com/ |
| `LANGFUSE_SECRET_KEY` (optional) | Same as above | — |
| `LANGFUSE_HOST` (optional, default `https://cloud.langfuse.com`) | Set to `https://us.cloud.langfuse.com` for the US region or your self-hosted URL | — |

## Using the app

**Chat tab** — ask questions about your indexed documents *and* the SQL warehouse. Each turn runs the **adaptive router** first to pick a strategy, then dispatches: vector queries hit Qdrant (dense + BM25 + RRF + cross-encoder rerank, top `RERANK_TOP_K` chunks); SQL queries hit Postgres read-only with safety guards. Inline `[n]` citations resolve to chunks, `[DB]` to the executed query. The **Sources** panel on the right shows the router's decision + reasoning, the executed SQL with its first 5 rows, and the cited chunks with rerank scores. The footer line shows per-stage timings (routing / retrieval / sql / synthesis / total).

**Ingest tab** — multi-file ingestion. Each file is converted → chunked → upserted into Qdrant. The library on the right shows what's currently indexed and lets you delete by `doc_id`. Re-ingesting a file by default replaces its previous chunks; tick **Skip if already indexed** to no-op instead.

**Convert tab** — single-document preview; pick a file, optionally force Qwen for PDFs, see the markdown and download.

**Admin tab** — token + USD cost rollups pulled from Langfuse. Disabled-state instructions when `LANGFUSE_*` keys are missing.

## Evaluation

```bash
# Router-only accuracy (cheap, ~10 LLM calls). Exits non-zero if accuracy
# drops below 85% — drop this into CI to catch prompt regressions.
uv run python -m src.eval.run_routing_eval

# Full pipeline through Ragas (faithfulness / response relevancy /
# context precision). Generates JSON + a self-contained HTML report
# under src/eval/reports/.
uv run python -m src.eval.run_ragas

# Quick cost snapshot from the CLI (or use the Admin tab).
uv run python -m src.observability.cost_tracker --days 7
```

## Roadmap

- ✅ Phase 1: Docling baseline document conversion
- ✅ Phase 2: Parser router (Docling + Qwen3-VL fallback) with caching
- ✅ Phase 3: Header-aware chunking + hybrid (dense + BM25) Qdrant indexing
- ✅ Phase 4: Hybrid retrieval + FlashRank reranker + grounded chat with citations
- ✅ Phase 5: Adaptive query router + read-only SQL tool over a demo Postgres warehouse
- ✅ Phase 6: Langfuse tracing + cost dashboard + routing eval + Ragas runner
- ⏸️ Phase 7: C-RAG self-reflection, MCP server surface, web fallback, streaming

Full plan in `PROJECT_PLAN.md`.

## License

MIT
