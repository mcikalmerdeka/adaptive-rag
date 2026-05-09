# AdaptiveRAG — Architecture

A hybrid Adaptive RAG system. Each query is classified at runtime into one of five execution strategies (`no_retrieval`, `vector_only`, `sql_only`, `hybrid`, `clarify`) and dispatched to the right backend(s). Documents flow through a markdown-first ingestion pipeline; the retrieval layer is hybrid (dense + BM25 + cross-encoder rerank); the SQL layer is read-only with defense in depth.

---

## Table of Contents

1. [Goals & Non-Goals](#1-goals--non-goals)
2. [Core Principles](#2-core-principles)
3. [System Overview](#3-system-overview)
4. [Tech Stack](#4-tech-stack)
5. [Project Structure](#5-project-structure)
6. [Ingestion Pipeline](#6-ingestion-pipeline)
7. [Chunking Strategy](#7-chunking-strategy)
8. [Retrieval Layer](#8-retrieval-layer)
9. [Adaptive Query Router](#9-adaptive-query-router)
10. [Tool Layer (Read-Only SQL)](#10-tool-layer-read-only-sql)
11. [Synthesis & Citations](#11-synthesis--citations)
12. [Caching & Cost Control](#12-caching--cost-control)
13. [Configuration](#13-configuration)
14. [Implementation Status](#14-implementation-status)
15. [Decision Log](#15-decision-log)
16. [Future Work](#16-future-work)

---

## 1. Goals & Non-Goals

### Goals

- **Adaptive retrieval** — pick the right strategy per-query, not per-file-extension.
- **Markdown-first ingestion** — convert every input format to markdown so chunks are header-aware.
- **Hybrid retrieval at the index layer** — dense embeddings + BM25 + reciprocal-rank fusion + cross-encoder reranker.
- **Grounded answers with citations** — inline `[n]` markers for chunks, `[DB]` for SQL data, parsed back into structured citations for the UI.
- **Cost-bounded** — content-hash caches for OCR and embeddings; cheap models for routing, frontier models only for synthesis.
- **Portfolio-presentable** — clean code, working demo, real metrics in Phase 6.

### Non-Goals

- Multi-tenant SaaS with RBAC.
- Real-time CDC / database mirroring into vectors. (See decision log: never embed structured data.)
- Distributed task queue. `FastAPI BackgroundTasks` is enough until proven otherwise.
- A constellation of MCP servers. One optional MCP surface that wraps the same tools is enough.
- Production monitoring stack (Prometheus / Grafana / Jaeger). Langfuse for traces is enough.

---

## 2. Core Principles

1. **If the answer is a sentence, embed it. If the answer is a number, query it.** Free text goes to vectors; structured data stays in SQL.
2. **Decide adaptively at query time, not at ingest time.** A PDF can contain prose *and* tables; a SQL row can have a free-text comment. Routing has to see the question, not just the file.
3. **Markdown is the universal intermediate format.** Every parser output normalizes to markdown before chunking.
4. **Quality of parsing beats quantity of features.** One excellent ingestion path is better than five mediocre ones.
5. **Measure before optimizing.** No reranker, no advanced chunking, no MCP — until eval scores justify each addition.

---

## 3. System Overview

```
┌──────────────────────────────────────────────────────────────────────┐
│                         INGESTION (offline)                           │
│                                                                       │
│  File ─► FileTypeDetector ─► ParserRouter ─► Markdown ─► Chunker      │
│                                  │                                    │
│                                  ├─ Docling          (default)        │
│                                  ├─ Qwen3-VL         (image / scan)   │
│                                  └─ passthrough      (.md, .txt)      │
│                                                                       │
│  Markdown ─► MarkdownHeaderSplitter ─► Embedder ─► Qdrant             │
│                                            │                          │
│                                            ├─ dense  (text-emb-3)     │
│                                            └─ sparse (BM25 / IDF)     │
└──────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────┐
│                         QUERY-TIME (online)                           │
│                                                                       │
│   user query                                                          │
│       │                                                               │
│       ▼                                                               │
│  ┌──────────────────────┐                                             │
│  │ AdaptiveRouter       │   cheap LLM classifier                      │
│  │  → strategy + intent │   (gpt-4.1-nano default)                    │
│  └────────┬─────────────┘                                             │
│           │                                                           │
│   ┌───────┼───────────┬─────────────┬────────────────┐                │
│   ▼       ▼           ▼             ▼                ▼                │
│ no_retr.  vector    sql_only      hybrid          clarify             │
│  (LLM)   ↓ Qdrant   ↓ NL→SQL     ↓ both           (ask user)          │
│          ↓ + rerank ↓ + execute  ↓ + merge                            │
│           └──────────┴────────────┘                                   │
│                      │                                                │
│                      ▼                                                │
│             GroundedAnswerer (LLM)                                    │
│                      │                                                │
│                      ▼                                                │
│        answer with [n] / [DB] citations                               │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 4. Tech Stack

| Component | Library | Role |
|---|---|---|
| Document parsing | `docling>=2.92` | Born-digital PDFs, DOCX, PPTX, XLSX, HTML, CSV |
| OCR | `openai>=2.33` against DashScope OpenAI-compat endpoint | Qwen3-VL-Plus for images and scanned PDFs |
| LLM framework | `langchain>=1.2`, `langchain-core>=1.3` | Message types, prompts, structured output |
| LLM client | `langchain-openai>=1.2` | Chat synthesis, router, NL→SQL |
| Embeddings — dense | `langchain-openai` + `text-embedding-3-small` | 1536-dim, with SHA256 disk cache |
| Embeddings — sparse | `fastembed>=0.4` (`Qdrant/bm25`) | Local BM25 with IDF, no GPU |
| Vector DB | `qdrant-client>=1.12` + `langchain-qdrant>=1.1` | Hybrid collection (dense + sparse named vectors) |
| Reranker | `flashrank>=0.2.9` | Pure-ONNX cross-encoder (`ms-marco-MiniLM-L-12-v2`, ~34 MB) |
| Splitters | `langchain-text-splitters>=1.1` | Header-aware + recursive fallback |
| PDF inspection | `pypdfium2>=4.30` | Born-digital heuristic + page rendering |
| Schema validation | `pydantic>=2.9` | Structured router output, structured NL→SQL |
| SQL | `sqlalchemy>=2.0.36` + `psycopg[binary]>=3.2.3` | Read-only Postgres tool |
| Retry | `tenacity>=9.x` | Qwen API resilience |
| UI | `gradio>=6.13` | Tabbed Chat / Ingest / Convert demo |
| Env | `python-dotenv>=1.2` | `.env` config loader |

### Explicitly avoided

- `celery`, `redis` — not needed; `FastAPI BackgroundTasks` is sufficient.
- `transformers`, `torch`, `accelerate` — Qwen is API-based and FlashRank uses ONNX. Keeps the install lean and dodges Python-3.14 native-extension instability.
- `watchdog` — explicit upload via UI/API is fine.
- CDC tooling (Debezium et al.) — query DB live via tool, never sync.
- Prometheus / Grafana — Langfuse covers it for v1.

---

## 5. Project Structure

```
adaptive-rag/
├── app.py                          Gradio entry point
├── pyproject.toml
├── docker-compose.yml              Qdrant + Postgres
├── .env.example
├── ARCHITECTURE.md                 (this file)
├── README.md
├── PROJECT_PLAN.md                 Phase-by-phase status
├── scripts/
│   ├── init_qdrant.py              Create / recreate the Qdrant collection
│   └── seed_demo_data.py           Seed Postgres with demo e-commerce data
│
├── src/
│   ├── config/
│   │   └── settings.py             Single source of truth for all tunables
│   │
│   ├── core/                       Document → markdown
│   │   ├── file_detector.py        Format detection + validation
│   │   ├── docling_parser.py       Docling-backed parser
│   │   ├── qwen_parser.py          Qwen3-VL OCR with retry + cache
│   │   ├── parser_router.py        Picks Docling vs Qwen per file
│   │   └── converter.py            Public conversion API
│   │
│   ├── chunking/                   Markdown → header-aware chunks
│   │   ├── markdown_chunker.py     Header splitter + recursive fallback
│   │   └── metadata.py             doc_id (SHA256), chunk_uuid (UUID5)
│   │
│   ├── indexing/                   Chunks → Qdrant
│   │   ├── embeddings.py           Dense (cached) + BM25 sparse
│   │   ├── qdrant_store.py         Hybrid collection + dedup + library
│   │   └── pipeline.py             Convert → chunk → upsert
│   │
│   ├── retrieval/                  Query → ranked chunks
│   │   ├── hybrid_search.py        HybridRetriever + RetrievalPipeline
│   │   └── reranker.py             FlashRank ONNX cross-encoder
│   │
│   ├── routing/                    Adaptive router + dispatcher
│   │   ├── strategies.py           Strategy StrEnum + capability sets
│   │   ├── prompts.py              Router system prompt + few-shots
│   │   ├── adaptive_router.py      LLM classifier (structured output)
│   │   └── dispatcher.py           Compose router + retrieval + SQL + synthesis
│   │
│   ├── tools/                      External tools the dispatcher can call
│   │   └── sql_tool.py             Read-only NL→SQL with safety guards
│   │
│   ├── synthesis/                  Chunks (+ SQL) → grounded answer
│   │   └── response.py             GroundedAnswerer + Citation parsing
│   │
│   ├── cache/                      Content-hash caches
│   │   ├── ocr_cache.py            SHA256-keyed disk cache for OCR markdown
│   │   └── embedding_cache.py      SHA256-keyed disk cache for vectors
│   │
│   ├── utils/
│   │   └── pdf_inspector.py        Born-digital heuristic + page rendering
│   │
│   └── ui/                         Gradio interface
│       ├── main_ui.py              Tab composition
│       ├── chat_ui.py              Chat tab (calls AdaptiveDispatcher)
│       ├── ingest_ui.py            Ingest tab (multi-file upload + library)
│       └── markdown_converter_ui.py  Convert tab (single-document preview)
│
└── docs/
    ├── check_postgres.md           DB inspection cheatsheet
    └── check_qdrant.md             Vector DB inspection cheatsheet
```

---

## 6. Ingestion Pipeline

### Parser routing

```
file_type ──┐
            ├── .md / .txt ──────────────────► passthrough
            │
            ├── .pdf ──┬─ "born-digital" ───► Docling   (fast, text layer)
            │         └─ "scanned"  ────────► Qwen3-VL  (vision)
            │
            ├── .docx / .pptx / .xlsx / .html / .csv ──► Docling
            │
            └── .png / .jpg / .webp ──► Qwen3-VL  (better than Tesseract on layout)
```

The "born-digital vs scanned" decision for PDFs is a cheap heuristic: render the text layer of the first three pages and treat the file as scanned if the total extracted character count is below a small threshold. Docling has its own internal OCR fallback (EasyOCR / Tesseract); the heuristic lets us skip that path and use Qwen3-VL when accuracy matters.

The user can override this routing per-file with a "Force Qwen3-VL OCR for PDFs" toggle in the Convert tab.

### Qwen3-VL OCR

Calls the DashScope OpenAI-compatible endpoint. The OCR prompt is intentionally deterministic:

> Extract all text from this image into clean GitHub-flavored Markdown. Preserve table structure with pipe syntax. Preserve heading hierarchy. Do not summarize, do not add commentary. If text is illegible, write `[illegible]`.

`tenacity` handles transient API failures with exponential backoff. The result is content-hash cached so re-uploading the same file (or re-rendering the same page from a multi-page PDF) never spends a second API call.

### Content-hash everything

Three things use SHA256 as a primary key:

| Cache | Key | Stored |
|---|---|---|
| OCR | `sha256(image_bytes)` | Markdown text on disk |
| Embeddings | `sha256(model_name + text)` | Raw `float32` vector bytes on disk |
| Documents | `sha256(file_bytes)[:16]` | `doc_id` for dedup + library listing |

Re-ingesting the same file replaces its prior chunks in Qdrant atomically (delete-by-`doc_id` then upsert).

---

## 7. Chunking Strategy

Two-pass:

1. **`MarkdownHeaderTextSplitter`** splits by `#`, `##`, `###`. Headers are kept in the chunk content and the header path is also written to chunk metadata.
2. **`RecursiveCharacterTextSplitter`** splits any header-section that exceeds `CHUNK_SIZE` (default 1500 chars). Each sub-chunk inherits the parent's header path.

### Per-chunk metadata

```json
{
  "doc_id":        "dc7c3912cd0b003d",
  "source":        "data/policy.pdf",
  "filename":      "policy.pdf",
  "header_path":   "Refund Policy > Eligibility",
  "chunk_index":   7,
  "total_chunks":  23,
  "ingested_at":   "2026-05-09T04:52:24+00:00",
  "parser":        "docling"      // or "qwen3-vl" or "passthrough"
}
```

`chunk_uuid` is generated deterministically via `UUID5(doc_id, chunk_index)` so re-upserts are idempotent.

No `access_level` / `department` / `tags` in v1 — those go in only when a feature actually consumes them.

---

## 8. Retrieval Layer

### Qdrant collection: hybrid by default

```python
client.create_collection(
    collection_name="adaptive_rag",
    vectors_config={
        "dense": models.VectorParams(size=1536, distance=models.Distance.COSINE),
    },
    sparse_vectors_config={
        "bm25": models.SparseVectorParams(modifier=models.Modifier.IDF),
    },
)
```

Both vectors are populated for every chunk at ingest time; queries hit both.

### Query flow

```
query
  │
  ├─► dense embedding   (text-embedding-3-small, cached)
  ├─► sparse encoding   (FastEmbed BM25, IDF on server)
  │
  ▼
Qdrant `query_points` with prefetch:
  - prefetch dense  (top RETRIEVAL_PREFETCH_K = 25)
  - prefetch sparse (top RETRIEVAL_PREFETCH_K = 25)
  - fusion: server-side RRF
  │
  ▼
FlashRank cross-encoder rerank
  → top RERANK_TOP_K = 5
  │
  ▼
Pass to GroundedAnswerer with header_path context
```

The fusion is server-side RRF (Qdrant native), not client-side merging — single round-trip per query.

The reranker uses `ms-marco-MiniLM-L-12-v2` by default (~34 MB ONNX). Lazy first-use download to `CACHE_DIR/flashrank/`. If model loading or scoring fails, the pipeline gracefully falls back to the hybrid-fusion order. Alternatives configurable via `RERANKER_MODEL`:

| Model | Size | Notes |
|---|---|---|
| `ms-marco-TinyBERT-L-2-v2` | ~4 MB | Fastest |
| `ms-marco-MiniLM-L-12-v2` | ~34 MB | **Default** — balanced |
| `ms-marco-MultiBERT-L-12` | ~150 MB | Multilingual |
| `rank-T5-flan` | ~110 MB | Best quality |

Hybrid search typically yields **+5–15% retrieval recall** over pure dense; reranking adds another **+10–20% context precision** on top. Numbers will be re-validated against the golden set in Phase 6.

---

## 9. Adaptive Query Router

The router is what makes this *Adaptive RAG* (per Jeong et al., 2024 — query-complexity-aware strategy selection) rather than static dispatch.

### Strategies

| Strategy | When | Touches |
|---|---|---|
| `no_retrieval` | Greeting, chitchat, generic knowledge, math | LLM only |
| `vector_only` | Conceptual / "what does our doc say about X" | Qdrant + reranker + LLM with `[n]` citations |
| `sql_only` | Quantitative / "how many" / "top N" / aggregates | NL→SQL → execute → LLM with `[DB]` citation |
| `hybrid` | Question needs both narrative AND a number | Vector AND SQL → blended answer |
| `clarify` | Genuinely ambiguous | One focused follow-up question, no retrieval cost |

### How a decision is made

A single LLM call with structured output. The classifier model is intentionally cheap (`gpt-4.1-nano` by default) — classification doesn't need frontier reasoning, and we want this on the hot path of every chat turn.

```python
class RouterDecision(BaseModel):
    strategy: Strategy                   # one of the five above
    reasoning: str                        # one-sentence justification
    vector_query: str | None              # optional rephrased search query
    sql_intent: str | None                # NL description for the SQL tool
    clarification_question: str | None    # only set when strategy == clarify
```

The router prompt includes:
1. Strategy descriptions + few-shot examples (anchors classification).
2. The actual chat history (so follow-ups like "what about last quarter?" can resolve to a real referent instead of always falling to `clarify`).
3. A one-line summary of available SQL tables — fetched via `inspect()` once at startup. ~80 tokens. Lets the router decide "this is a database question" vs "this is a docs question."

If `SQL_DATABASE_URL` is unset, the prompt is told "no SQL backend" and a sanitizer downgrades any leaked `sql_only`/`hybrid` decision to `vector_only`. The router can never pick a strategy it can't fulfill.

### Dispatch

`AdaptiveDispatcher.answer(query, history)` is the single entry point the chat UI calls. It:

1. Classifies the query.
2. For `clarify` / `no_retrieval`: short-circuits without touching retrieval or SQL.
3. For `vector_only` / `hybrid`: runs the retrieval pipeline.
4. For `sql_only` / `hybrid`: runs the SQL tool. If the tool fails (DB down, query rejected), records a note and continues with whatever else it has.
5. Calls the appropriate `GroundedAnswerer` method.
6. Returns an `AdaptiveAnswer` with strategy, decision, citations, executed SQL, and per-stage timings.

Backends are initialized lazily on first use so the app starts fast even when SQL or OpenAI aren't configured.

---

## 10. Tool Layer (Read-Only SQL)

### Defense in depth

The SQL tool is *not* an agent. It runs once per turn, with five layers of safety:

1. **Dedicated read-only Postgres role.** `seed_demo_data.py` creates `adaptive_rag_ro` with `SELECT`-only grants. The app connects as that role.
2. **Statement-level allowlist.** Only `SELECT` and `WITH` (CTE-resolved-to-SELECT) statements are accepted.
3. **Forbidden-keyword regex.** Catches `INSERT|UPDATE|DELETE|MERGE|TRUNCATE|DROP|ALTER|CREATE|GRANT|REVOKE|COPY|VACUUM|...` even if the role grants would already block them.
4. **Per-session statement timeout.** Default 5 seconds (`SQL_QUERY_TIMEOUT_SEC`); runaway plans die fast.
5. **Implicit row cap.** A `LIMIT N` (default 200, `SQL_ROW_LIMIT`) is appended if the SQL doesn't already cap rows.

Plus `SET TRANSACTION READ ONLY` on every connection — belt + suspenders + bungee.

### NL → SQL

A second LLM call (`gpt-4.1-mini` by default, `SQL_MODEL`) translates the router's `sql_intent` into a single `SELECT`. Schema is included in the prompt — generated once via SQLAlchemy `inspect()` at startup, formatted as DDL-style table descriptions with column types, primary keys, and foreign keys.

Structured output forces a `_SqlOutput { sql: str }` schema, so the LLM can't dump prose around the query.

### Demo dataset

`scripts/seed_demo_data.py` builds a deterministic e-commerce schema:

```
customers   (100 rows)  — id, name, email, country, signup_date
products    (50 rows)   — id, name, category, price, stock
orders      (500 rows)  — id, customer_id, status, total, created_at
order_items (~1300 rows) — id, order_id, product_id, quantity, unit_price
refunds     (~35 rows)  — id, order_id, amount, reason, created_at
```

Idempotent (skips if already populated) with `--recreate` to wipe and reseed. The fixed RNG seed gives the same data every run, so demos and golden-set evals are reproducible.

### Optional MCP surface (Phase 7)

The same `SqlTool` and retrieval pipeline can be exposed as an MCP server so Cursor / Claude Desktop can use them without the Gradio UI. This is the *correct* use of MCP — making the same capabilities reusable across LLM clients — not as a microservice framework.

---

## 11. Synthesis & Citations

`GroundedAnswerer` has three modes that the dispatcher selects:

| Method | Used for | Context shape |
|---|---|---|
| `answer_direct` | `no_retrieval` | Just the user query + chat history |
| `answer` | `vector_only` | Numbered passage block `[1]..[N]` |
| `answer_with_sql` | `sql_only` / `hybrid` | Passages **plus** a "Database query results" section with the executed SQL and a markdown-rendered preview of rows |

### Citation contract

The system prompt requires inline brackets for every claim:

- `[1]`, `[2, 3]` — refer to chunk numbers in the passage block.
- `[DB]` — refers to the SQL results block (only valid when SQL data is present).

The chat layer parses the LLM's output back into structured citations:

```python
@dataclass
class Citation:
    index: int            # 1-based chunk number
    label: str            # "policy.pdf > Refunds"
    snippet: str          # short preview
    source: str | None
    doc_id: str | None
    rank: int
    rerank_score: float | None
    hybrid_score: float
```

Only chunks the LLM actually cited end up in the right-hand Sources panel — clean UI by default, with a debug mode that surfaces all retrieved chunks if the LLM cites none. The `cited_db` boolean flag drives a separate "SQL executed" block in the panel.

---

## 12. Caching & Cost Control

Three caches on disk, all SHA256-keyed:

| Cache | Key | Rationale |
|---|---|---|
| OCR | `sha256(image_bytes)` | Qwen3-VL is paid per-call. Re-ingest of the same image must never re-OCR. |
| Dense embeddings | `sha256(model_name + text)` | OpenAI is paid per-token. Re-chunking with the same content must not re-embed. |
| Reranker model | FlashRank's own | First-use download (~34 MB), reused thereafter. |

Default location is `./.cache/`, override with `CACHE_DIR`.

Cost-per-query in the current configuration is dominated by the synthesis LLM (`gpt-4.1-mini`). Routing (`gpt-4.1-nano`) is roughly 1/10th the cost; SQL translation is one extra mini-call only when needed. A live cost tracker is Phase 6 work.

---

## 13. Configuration

Every tunable lives in `src/config/settings.py` — a frozen `Settings` dataclass loaded once from `.env` via `python-dotenv`. Some highlights:

| Setting | Default | What |
|---|---|---|
| `OPENAI_API_KEY` | (required) | Embeddings, router, SQL gen, synthesis |
| `QWEN_API_KEY` | (required for OCR) | DashScope endpoint |
| `QDRANT_URL` | `http://localhost:6333` (or unset → embedded mode) | Vector DB |
| `QDRANT_COLLECTION` | `adaptive_rag` | Collection name |
| `DENSE_MODEL` | `text-embedding-3-small` | Must match `DENSE_SIZE` |
| `DENSE_SIZE` | `1536` | Vector dimensions |
| `SPARSE_MODEL` | `Qdrant/bm25` | FastEmbed BM25 |
| `CHUNK_SIZE` / `CHUNK_OVERLAP` | `1500` / `200` | Recursive splitter |
| `RETRIEVAL_PREFETCH_K` | `25` | Candidates fetched before rerank |
| `RERANK_TOP_K` | `5` | Final chunks shown to the LLM |
| `RERANKER_MODEL` | `ms-marco-MiniLM-L-12-v2` | FlashRank model |
| `LLM_MODEL` | `gpt-4.1-mini` | Synthesis |
| `LLM_TEMPERATURE` | `0.2` | |
| `ROUTER_MODEL` | `gpt-4.1-nano` | Cheap classifier |
| `SQL_MODEL` | `gpt-4.1-mini` | NL→SQL translator |
| `SQL_DATABASE_URL` | (unset) | Leave unset to disable `sql_only` / `hybrid` strategies |
| `SQL_QUERY_TIMEOUT_SEC` | `5` | Per-query Postgres timeout |
| `SQL_ROW_LIMIT` | `200` | Implicit `LIMIT N` injection |
| `CACHE_DIR` | `./.cache` | OCR + embedding caches |

---

## 14. Implementation Status

| Phase | Status | Description |
|---|---|---|
| 0. Setup & infra | ✅ | Repo, deps, Docker compose, settings |
| 1. Docling baseline | ✅ | Document → markdown for native formats |
| 2. Parser router + Qwen | ✅ | Born-digital vs scanned heuristic, Qwen3-VL OCR with cache |
| 3. Chunking + indexing | ✅ | Header-aware chunks, hybrid Qdrant collection, dedup |
| 4. Retrieval + chat | ✅ | Hybrid search + RRF + FlashRank + grounded answers with `[n]` citations |
| 5. Adaptive router + SQL | ✅ | Five-strategy router, read-only SQL tool, `[DB]` citations |
| 6. Eval + tracing + polish | ⬜ | Ragas golden set, Langfuse, cost tracker, docs |
| 7. Stretch | ⏸️ | C-RAG self-reflection, multi-hop, MCP server, web fallback |

See `PROJECT_PLAN.md` for the full phase-by-phase task list and acceptance criteria.

---

## 15. Decision Log

| Decision | Chosen | Rejected | Reason |
|---|---|---|---|
| Routing layer | Query-time LLM classifier | Ingest-time extension matching | A PDF can have prose AND tables; routing must see the question |
| Document parser | Docling | LangChain native loaders, LlamaParse, Marker | Free, local, table-aware, multi-format |
| OCR | Qwen3-VL-Plus (API) | GLM-OCR (self-hosted), EasyOCR, Tesseract | No GPU, better quality on complex layouts, cheap per-image |
| Vector DB | Qdrant | pgvector, Weaviate, Chroma | Best hybrid (dense + sparse) support, server-side RRF |
| Sparse encoder | BM25 via FastEmbed | SPLADE, no sparse | Free, fast, no GPU |
| Reranker | FlashRank `ms-marco-MiniLM-L-12-v2` | BGE-reranker-v2-m3 (Torch), Cohere Rerank (paid), ColBERT | Pure ONNX via `onnxruntime` (already pulled by `fastembed`); no Torch / Transformers; sidesteps Python-3.14 native-extension instability we hit with `py-rust-stemmers` |
| Router LLM | `gpt-4.1-nano` | `gpt-4.1-mini`, `claude-haiku` | Cheapest model that classifies reliably; classification doesn't need frontier reasoning |
| Synthesis LLM | `gpt-4.1-mini` | `gpt-4.1`, `gpt-4o-mini` | Strong enough to follow citation rules, cheap enough for hot path |
| Tool protocol | Native Python class with explicit dispatch | OpenAI function calling registry, MCP for everything | We're not an agent loop — the router *picks* a strategy, then we run it. Registry abstraction is dead weight. MCP only when external clients consume. |
| SQL backend | Postgres in Docker bound to host port 5433 | Default 5432, SQLite, Neon | 5433 sidesteps collisions with host-installed Postgres on 5432; users can swap to Neon by changing `SQL_DATABASE_URL` |
| Read-only enforcement | Dedicated DB role + statement allowlist + keyword regex + statement_timeout + LIMIT injection + READ ONLY transaction | Just one of those | Defense in depth — any one layer might be misconfigured |
| Task queue | `BackgroundTasks` | Celery + Redis | YAGNI; add when measured queue depth justifies it |
| File watching | Manual upload | watchdog filesystem watcher | UI-driven flow is enough; watcher is feature creep |
| DB sync to vectors | Live SQL tool, query at runtime | CDC (Debezium et al.) | Core principle: never embed structured data |
| Eval | Ragas + custom routing-accuracy metric | None / vibes-based | Portfolio projects without metrics look unfinished |
| Tracing | Langfuse | Prometheus + Grafana + Jaeger | LLM-native, single signup, free tier |

---

## 16. Future Work

### Phase 6 — Eval, tracing, polish

- `src/eval/golden.jsonl` — 30–50 Q&A pairs across all five strategies, including adversarial / edge cases.
- `src/eval/ragas_runner.py` — faithfulness, answer relevancy, context precision, context recall + an HTML report.
- Routing-accuracy metric on the golden set, gated in CI (fail on >5% regression).
- Langfuse spans on every dispatcher stage (router → retrieval → SQL → synthesis), including token counts and per-call cost.
- `src/observability/cost_tracker.py` + a Gradio admin tab showing daily / weekly cost breakdown.
- README polish — demo gif, screenshots, eval scores baked in.

### Phase 7 — Stretch

- **C-RAG self-reflection.** Grade retrieved context for relevance; on low scores, re-route or fall back to web search.
- **Multi-hop retrieval.** When `clarify` would have been picked, escalate to step-by-step iterative search instead of asking the user.
- **MCP server.** Expose `search_docs` and `query_sql` so Cursor / Claude Desktop can use the same tools.
- **Web search fallback.** Tavily / Exa when local context is insufficient.
- **Streaming responses.** Wire LLM streaming through Gradio for snappier UX.
- **Multi-collection Qdrant.** Split per-domain (`policies`, `finance`, `technical`) once ingest volume justifies the operational cost.
- **Image-in-markdown OCR.** Extract images from Docling output, OCR them with Qwen, inline the text into the parent markdown.

---

**End of architecture document.**
