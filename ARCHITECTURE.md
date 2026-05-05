# AdaptiveRAG — Architecture

**Hybrid Adaptive RAG with query-time strategy selection, markdown-first ingestion, and optional MCP tool surface.**

> Supersedes `inspiration/intelligent_data_platform_documentation.md`. That doc was over-engineered for the actual goal: it routed at ingestion time (static dispatch) instead of query time (adaptive), used MCP as a generic microservice framework, and pulled in CDC/Celery/Redis without a real driver. This document is the lean replacement.

---

## Table of Contents

1. [Goals & Non-Goals](#1-goals--non-goals)
2. [Core Principles](#2-core-principles)
3. [System Overview](#3-system-overview)
4. [Tech Stack](#4-tech-stack)
5. [Project Structure](#5-project-structure)
6. [Ingestion Pipeline](#6-ingestion-pipeline)
7. [Chunking Strategy](#7-chunking-strategy)
8. [Retrieval Layer (Hybrid Search + Rerank)](#8-retrieval-layer-hybrid-search--rerank)
9. [Adaptive Query Router (The Actual Brain)](#9-adaptive-query-router-the-actual-brain)
10. [Tool Layer (SQL + Optional MCP)](#10-tool-layer-sql--optional-mcp)
11. [Evaluation Framework](#11-evaluation-framework)
12. [Caching & Cost Control](#12-caching--cost-control)
13. [Phased Implementation Plan](#13-phased-implementation-plan)
14. [Decision Log](#14-decision-log)
15. [Open Questions](#15-open-questions)

---

## 1. Goals & Non-Goals

### Goals
- **Adaptive retrieval** — pick `no-retrieval | vector | sql-tool | hybrid` per-query, not per-file-extension.
- **Markdown-first ingestion** — convert everything to markdown via Docling so chunks are header-aware.
- **Hybrid retrieval at the index layer** — dense embeddings + sparse (BM25) + reranker.
- **Honest evaluation** — Ragas metrics on a small golden set from day one.
- **Cost-bounded** — cache OCR and embeddings by content hash; track per-query cost.
- **Portfolio-presentable** — clean code, working demo, real metrics.

### Non-Goals
- Multi-tenant SaaS with RBAC.
- Real-time CDC / database mirroring into vectors.
- Distributed task queue (Celery/Redis) — `FastAPI BackgroundTasks` is enough until proven otherwise.
- 4 separate MCP servers — one optional MCP surface that wraps the same tools.
- Production monitoring (Prometheus/Grafana) — Langfuse for traces is enough.

---

## 2. Core Principles

1. **If the answer is a sentence → embed it. If the answer is a number → query it.** (Original principle, kept.)
2. **Decide adaptively at query time, not at ingest time.** A PDF can contain prose *and* tables; a SQL DB row can have a free-text comment column. Routing happens after we read the question, not when the file lands on disk.
3. **Markdown is the universal intermediate format.** Every parser output normalizes to markdown before chunking.
4. **Quality of parsing > quantity of features.** One excellent ingestion path beats five mediocre ones.
5. **Measure before optimizing.** No reranker, no advanced chunking, no MCP — until eval scores justify each addition.

---

## 3. System Overview

```
┌──────────────────────────────────────────────────────────────────────┐
│                         INGESTION (Offline)                           │
│                                                                       │
│  File ──▶ FileTypeDetector ──▶ Parser ──▶ Markdown ──▶ Chunker        │
│                                  │                                     │
│                                  ├─ Docling (default)                  │
│                                  ├─ Qwen3-VL (image / scanned PDF)     │
│                                  └─ passthrough (.md, .txt)            │
│                                                                       │
│  Markdown ──▶ MarkdownHeaderSplitter ──▶ Embedder ──▶ Qdrant          │
│                                            │                           │
│                                            ├─ Dense (text-emb-3-small) │
│                                            └─ Sparse (BM25 / SPLADE)   │
└──────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────┐
│                       QUERY-TIME (Online)                             │
│                                                                       │
│   User Query                                                          │
│       │                                                               │
│       ▼                                                               │
│  ┌──────────────────────┐                                             │
│  │ Adaptive Router      │  (cheap LLM classifier)                     │
│  │  → strategy: A/B/C/D │                                             │
│  └──────┬───────────────┘                                             │
│         │                                                             │
│   ┌─────┼──────────────┬─────────────┬────────────────┐               │
│   ▼     ▼              ▼             ▼                ▼               │
│  none  vector        sql-tool      hybrid           clarify           │
│         │              │             │                                │
│         ▼              ▼             ▼                                │
│   Qdrant hybrid     SQL via       both, then                          │
│    + Reranker       function-call synthesize                          │
│         │              │             │                                │
│         └──────────────┴─────────────┘                                │
│                        │                                              │
│                        ▼                                              │
│                  Response Synthesizer                                 │
│                        │                                              │
│                        ▼                                              │
│                     Answer + Citations                                │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 4. Tech Stack

### Already in `pyproject.toml` (keep)

| Component | Library | Notes |
|---|---|---|
| Document parsing | `docling>=2.92` | Primary, handles PDF/DOCX/PPTX/XLSX/HTML/images |
| LLM framework | `langchain>=1.2` + `langchain-core` | v1.x — current API |
| Embeddings client | `langchain-openai>=1.2` | OpenAI SDK |
| Vector store | `langchain-qdrant>=1.1` | Hybrid (dense + sparse) supported |
| Splitters | `langchain-text-splitters>=1.1` | `MarkdownHeaderTextSplitter` lives here |
| UI | `gradio>=6.13` | Demo UI |
| OpenAI SDK | `openai>=2.33` | Also used for Qwen via DashScope OpenAI-compat endpoint |
| Env | `python-dotenv>=1.2` | |

### To add

| Component | Library | Why |
|---|---|---|
| Vector DB engine | `qdrant-client>=1.12` | Direct client for sparse vector config |
| Sparse encoder | `fastembed>=0.4` | BM25 / SPLADE-light, runs locally |
| Reranker | `sentence-transformers>=3.0` (BGE) **or** `cohere>=5.x` | Quality boost on top-k |
| Eval | `ragas>=0.2`, `datasets` | Faithfulness, context precision/recall |
| Tracing | `langfuse>=2.x` | LLM call traces, replaces ad-hoc logging |
| HTTP retry | `tenacity>=9.x` | For Qwen API resilience |
| SQL tool | `sqlalchemy>=2.x` | If/when SQL data source added |
| (Optional) MCP | `mcp>=1.x` | Only if exposing tools to external clients |

### To explicitly *not* add

- ~~`celery`, `redis`~~ — use `FastAPI BackgroundTasks`
- ~~`watchdog`~~ — explicit upload via UI/API is fine
- ~~`transformers`, `torch`, `accelerate`~~ — Qwen is API-based now
- ~~`debezium` / CDC~~ — query DB live via tool, never sync
- ~~Prometheus/Grafana stack~~ — Langfuse covers it for v1

---

## 5. Project Structure

Evolving from current state. Files marked `[exists]` are already implemented; `[new]` are planned.

```
adaptive-rag/
├── app.py                          [exists] Gradio entry point
├── pyproject.toml                  [exists]
├── ARCHITECTURE.md                 [this file]
├── README.md                       [exists, will update post Phase 2]
│
├── src/
│   ├── core/
│   │   ├── file_detector.py        [exists]
│   │   ├── converter.py            [exists] Docling-based MD converter
│   │   ├── ocr_qwen.py             [new] Qwen3-VL fallback OCR
│   │   └── parser_router.py        [new] Picks Docling vs Qwen per file
│   │
│   ├── chunking/
│   │   ├── markdown_chunker.py     [new] Header-aware + recursive fallback
│   │   └── metadata.py             [new] header_path, doc_id, hash
│   │
│   ├── indexing/
│   │   ├── embeddings.py           [new] Dense + sparse encoders
│   │   ├── qdrant_store.py         [new] Hybrid collection setup
│   │   └── deduplication.py        [new] Content-hash dedup
│   │
│   ├── retrieval/
│   │   ├── hybrid_search.py        [new] Fusion of dense + BM25
│   │   ├── reranker.py             [new] BGE / Cohere
│   │   └── citations.py            [new] Map chunks → source spans
│   │
│   ├── routing/
│   │   ├── adaptive_router.py      [new] THE adaptive bit
│   │   ├── strategies.py           [new] no-retrieval | vector | sql | hybrid
│   │   └── prompts.py              [new] Router system prompts
│   │
│   ├── tools/
│   │   ├── sql_tool.py             [new] Read-only SQL via function call
│   │   └── registry.py             [new] Tool schema for LLM
│   │
│   ├── synthesis/
│   │   └── response.py             [new] Combine context + tool results
│   │
│   ├── cache/
│   │   ├── ocr_cache.py            [new] SHA256-keyed disk cache
│   │   └── embedding_cache.py      [new] Same idea for embeddings
│   │
│   ├── eval/
│   │   ├── golden.jsonl            [new] ~30 Q&A pairs to start
│   │   ├── ragas_runner.py         [new]
│   │   └── reports/                [new] HTML eval reports
│   │
│   ├── observability/
│   │   ├── langfuse_client.py      [new]
│   │   └── cost_tracker.py         [new] $ per query, per ingest
│   │
│   ├── ui/
│   │   ├── markdown_converter_ui.py    [exists] Step 1 UI
│   │   ├── ingest_ui.py            [new] Upload → index
│   │   └── chat_ui.py              [new] Query interface
│   │
│   └── mcp_server/                 [optional, Phase 5]
│       └── server.py               Expose tools to Cursor/Claude Desktop
│
├── tests/
│   ├── test_chunking.py
│   ├── test_routing.py
│   ├── test_retrieval.py
│   └── fixtures/
│
└── docker-compose.yml              Qdrant only (postgres if SQL demo added)
```

---

## 6. Ingestion Pipeline

### Parser routing

```
file_type ──┐
            ├── .md / .txt ─────────────────► passthrough
            │
            ├── .pdf ──┬─ "born-digital" ───► Docling (fast, text layer)
            │         └─ "scanned"  ────────► Qwen3-VL (vision)
            │
            ├── .docx / .pptx / .xlsx / .html ► Docling
            │
            └── .png / .jpg / .tiff / .webp ──► Qwen3-VL (better than EasyOCR)
```

**How to decide born-digital vs scanned for PDFs:**

```python
def _is_scanned(pdf_path: Path) -> bool:
    """Heuristic: if first N pages have <50 chars of extractable text, treat as scanned."""
    import pypdf
    reader = pypdf.PdfReader(pdf_path)
    sample_pages = reader.pages[:3]
    total_text = sum(len(p.extract_text() or "") for p in sample_pages)
    return total_text < 150
```

Cheap, deterministic, good-enough heuristic. Docling internally does OCR fallback too; this just lets us skip Docling's OCR (EasyOCR/Tesseract) and use Qwen3-VL when accuracy matters.

### Qwen3-VL OCR (replaces GLM-OCR from old doc)

```python
# src/core/ocr_qwen.py
import base64, hashlib, os
from pathlib import Path
from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

class QwenOCR:
    def __init__(self):
        self._client = OpenAI(
            api_key=os.getenv("QWEN_API_KEY"),
            base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        )

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    def extract(self, image_path: Path) -> str:
        b64 = base64.b64encode(image_path.read_bytes()).decode()
        suffix = image_path.suffix.lstrip(".").lower()
        completion = self._client.chat.completions.create(
            model="qwen3-vl-plus",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/{suffix};base64,{b64}"}},
                    {"type": "text", "text": OCR_PROMPT},
                ],
            }],
        )
        return completion.choices[0].message.content
```

`OCR_PROMPT` should be deterministic and explicit:

> "Extract all text from this image into clean GitHub-flavored Markdown. Preserve table structure with pipe syntax. Preserve heading hierarchy. Do not summarize. Do not add commentary. If text is illegible, write `[illegible]`."

### Content-hash caching

Every parsed output is keyed by `sha256(file_bytes)`. Re-uploading the same scanned PDF should never call Qwen twice. See [§12 Caching](#12-caching--cost-control).

---

## 7. Chunking Strategy

Two-pass:

1. **`MarkdownHeaderTextSplitter`** — split by `#`, `##`, `###`. Inject the header path into chunk metadata.
2. **`RecursiveCharacterTextSplitter`** — fallback for any header-section that exceeds `max_chunk_size` (e.g. 1500 chars). Inherits the parent header_path.

```python
# src/chunking/markdown_chunker.py
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

HEADERS = [("#", "h1"), ("##", "h2"), ("###", "h3")]
header_splitter = MarkdownHeaderTextSplitter(headers_to_split_on=HEADERS, strip_headers=False)
recursive_splitter = RecursiveCharacterTextSplitter(
    chunk_size=1500, chunk_overlap=200,
    separators=["\n\n", "\n", ". ", " ", ""],
)

def chunk_markdown(md: str, doc_id: str) -> list[Document]:
    header_chunks = header_splitter.split_text(md)
    out = []
    for hc in header_chunks:
        # header_path = "h1 > h2 > h3" string
        path = " > ".join(v for k, v in hc.metadata.items() if k.startswith("h"))
        if len(hc.page_content) <= 1500:
            hc.metadata["header_path"] = path
            hc.metadata["doc_id"] = doc_id
            out.append(hc)
        else:
            for sub in recursive_splitter.split_text(hc.page_content):
                out.append(Document(
                    page_content=sub,
                    metadata={**hc.metadata, "header_path": path, "doc_id": doc_id},
                ))
    return out
```

**Metadata schema per chunk:**

```python
{
  "doc_id": "sha256(file)[:16]",
  "source": "data/policy.pdf",
  "filename": "policy.pdf",
  "header_path": "Refund Policy > Eligibility",
  "chunk_index": 7,
  "total_chunks": 23,
  "ingested_at": "2026-05-06T03:50:00Z",
  "parser": "docling" | "qwen3-vl" | "passthrough",
}
```

No `access_level`, `department`, `tags` etc. for v1 — add only when a feature needs them.

---

## 8. Retrieval Layer (Hybrid Search + Rerank)

### Qdrant collection: hybrid by default

```python
# src/indexing/qdrant_store.py
from qdrant_client import QdrantClient, models

COLL = "adaptive_rag"

def init_collection(client: QdrantClient, dense_size: int = 1536):
    client.create_collection(
        collection_name=COLL,
        vectors_config={
            "dense": models.VectorParams(size=dense_size, distance=models.Distance.COSINE),
        },
        sparse_vectors_config={
            "bm25": models.SparseVectorParams(modifier=models.Modifier.IDF),
        },
    )
```

### Query flow

```
query
  │
  ├─► dense embedding (text-embedding-3-small)
  ├─► sparse encoding (FastEmbed BM25)
  │
  ▼
Qdrant `query_points` with prefetch:
  - prefetch dense (top 25)
  - prefetch sparse (top 25)
  - fusion: RRF
  - limit: 12
  │
  ▼
Reranker (BGE-reranker-v2-m3 local OR cohere-rerank-3 API)
  → top 5
  │
  ▼
Pass to LLM with header_path context
```

Hybrid search (dense + sparse + RRF) typically buys you **+5-15% on retrieval recall** compared to pure dense. Reranker adds another **+10-20% on context precision**. These numbers are why the old doc's "dense only" recipe was leaving easy wins on the table.

---

## 9. Adaptive Query Router (The Actual Brain)

This is what makes the project actually "Adaptive RAG" (per Jeong et al., 2024 — query-complexity-aware strategy selection), not just static dispatch.

### Strategies

| ID | Name | When | Cost | Latency |
|---|---|---|---|---|
| `A` | `no_retrieval` | Greeting, chitchat, generic question | $ | low |
| `B` | `vector_only` | Conceptual / "what does X mean" / policy lookup | $$ | low |
| `C` | `sql_only` | Quantitative / "how many" / "what's the total" | $$ | low |
| `D` | `hybrid` | Mixed — needs both context and live numbers | $$$ | high |
| `E` | `clarify` | Ambiguous; ask user | $ | low |

### Implementation

```python
# src/routing/adaptive_router.py
from pydantic import BaseModel
from typing import Literal

class RouteDecision(BaseModel):
    strategy: Literal["no_retrieval", "vector_only", "sql_only", "hybrid", "clarify"]
    rationale: str
    rewritten_query: str | None = None  # optional query rewrite for retrieval
    sql_hint: str | None = None         # optional table/column hint for SQL tool

ROUTER_PROMPT = """\
You are a query router. Classify the user's query into ONE strategy:

- no_retrieval: greeting, chitchat, math, code generation that needs no docs/data
- vector_only: conceptual, policy, "what is", "how does", "explain"
- sql_only: numeric, aggregation, "how many", "total", "average", time-bounded counts
- hybrid: needs both context AND live numbers (e.g. "what's our refund policy and how many last month")
- clarify: ambiguous, missing context, multiple possible interpretations

Output strict JSON matching the schema. Rewrite the query for retrieval if useful (e.g. expand acronyms).
"""

def route(query: str, llm) -> RouteDecision:
    # Use a cheap fast model: gpt-4.1-nano or qwen-turbo
    return llm.with_structured_output(RouteDecision).invoke([
        {"role": "system", "content": ROUTER_PROMPT},
        {"role": "user", "content": query},
    ])
```

### Self-Reflection Loop (optional Phase 4)

After initial retrieval, run a grading step:

```
relevance_score = grader_llm("Is this context relevant to the query?", chunks, query)
if relevance_score < threshold:
    # Try web search, or expand to different collections, or escalate to hybrid
    fallback_strategy(...)
```

This is the C-RAG (Corrective RAG) pattern. Add it only after eval shows base routing is solid.

---

## 10. Tool Layer (SQL + Optional MCP)

### Default: native function calling, NO MCP

For the agent's own tools, use OpenAI/Anthropic function calling directly. MCP adds protocol overhead with no payoff when there's exactly one client (your own agent).

```python
# src/tools/sql_tool.py
from langchain_core.tools import tool
from sqlalchemy import create_engine, text

_engine = create_engine(os.getenv("DATABASE_URL"))

@tool
def query_sales(sql: str) -> str:
    """Run a READ-ONLY SQL query against the sales DB.
    Allowed tables: orders, refunds, customers.
    Must be a single SELECT. No DDL, DML, or comments."""
    if not _is_safe_select(sql):
        return "ERROR: only single SELECT statements allowed"
    with _engine.connect() as conn:
        rows = conn.execute(text(sql)).mappings().all()
    return json.dumps([dict(r) for r in rows[:100]], default=str)
```

`_is_safe_select` — simple guardrail: must start with `SELECT`, no `;` (single statement), regex blocklist for `INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|GRANT`. Run as a read-only DB user regardless.

### Optional: MCP surface (Phase 5, only if you want it)

Expose the same tools as an MCP server so Cursor / Claude Desktop can use them too:

```python
# src/mcp_server/server.py
from mcp.server.fastmcp import FastMCP
from src.tools.sql_tool import query_sales

mcp = FastMCP("adaptive-rag")

@mcp.tool()
def search_docs(query: str) -> str:
    """Hybrid vector + BM25 search across ingested documents."""
    return run_hybrid_search(query)

@mcp.tool()
def query_sales_db(sql: str) -> str:
    return query_sales.invoke({"sql": sql})
```

This is the *correct* use of MCP: making the same capabilities reusable across LLM clients. Not as a microservice framework.

---

## 11. Evaluation Framework

Eval-first development. Build the golden set *before* tuning chunk size or swapping rerankers.

### Golden set (`src/eval/golden.jsonl`)

```json
{"query": "What is our refund policy?", "expected_strategy": "vector_only", "expected_answer_contains": ["14 days", "original payment method"], "expected_sources": ["policy.pdf"]}
{"query": "How many refunds did we process last month?", "expected_strategy": "sql_only", "expected_answer_contains": ["1,247"]}
{"query": "Hi how are you", "expected_strategy": "no_retrieval"}
{"query": "What's our hiring policy and how many people did we hire in Q4?", "expected_strategy": "hybrid"}
```

Aim for **30-50 examples** spanning all 5 strategies, edge cases, and adversarial queries.

### Ragas metrics (per query)

| Metric | What it measures | Target |
|---|---|---|
| `faithfulness` | Answer grounded in retrieved context | >0.85 |
| `answer_relevancy` | Answer addresses the question | >0.85 |
| `context_precision` | Retrieved chunks are relevant | >0.75 |
| `context_recall` | All needed info was retrieved | >0.80 |

### Custom router metric

```python
def routing_accuracy(predictions, golden):
    correct = sum(p.strategy == g["expected_strategy"] for p, g in zip(predictions, golden))
    return correct / len(golden)
```

Run on every PR. Fail CI if regression > 5%.

---

## 12. Caching & Cost Control

Both Qwen3-VL and OpenAI embeddings cost real money. Without caching, dev iteration burns budget.

### OCR cache

```python
# src/cache/ocr_cache.py
import hashlib, json
from pathlib import Path

class OCRCache:
    def __init__(self, root: Path = Path(".cache/ocr")):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _key(self, image_bytes: bytes) -> str:
        return hashlib.sha256(image_bytes).hexdigest()

    def get(self, image_bytes: bytes) -> str | None:
        p = self.root / f"{self._key(image_bytes)}.md"
        return p.read_text(encoding="utf-8") if p.exists() else None

    def put(self, image_bytes: bytes, markdown: str) -> None:
        p = self.root / f"{self._key(image_bytes)}.md"
        p.write_text(markdown, encoding="utf-8")
```

Same pattern for embeddings (key = `sha256(text + model_name)`).

### Cost tracking

```python
# src/observability/cost_tracker.py
PRICES = {  # $/1k tokens or $/call — keep updated
    "gpt-4.1-nano": (0.10, 0.40),       # input, output per 1M
    "text-embedding-3-small": (0.02, 0),
    "qwen3-vl-plus": (0.0036, 0.012),   # per image, ~rough
    "cohere-rerank-3": (2.0, 0),        # per 1k searches
}
```

Log per-query cost to Langfuse. Surface daily/weekly totals in a Gradio admin tab.

---

## 13. Phased Implementation Plan

Each phase ends with a working, demonstrable artifact and an eval run.

### Phase 1 — Document → Markdown ✅ (done)
- `src/core/converter.py` (Docling) ✅
- `src/core/file_detector.py` ✅
- Gradio UI for upload + preview + download ✅

### Phase 2 — Add Qwen3-VL fallback + caching (1-2 days)
- `src/core/ocr_qwen.py`
- `src/core/parser_router.py` with born-digital vs scanned heuristic
- `src/cache/ocr_cache.py`
- UI toggle: "Force high-quality OCR (Qwen)"

### Phase 3 — Chunk + index (2-3 days)
- `src/chunking/markdown_chunker.py` (header-aware)
- `src/indexing/embeddings.py` (dense + sparse via FastEmbed)
- `src/indexing/qdrant_store.py` (hybrid collection)
- `src/cache/embedding_cache.py`
- Docker compose with Qdrant
- UI: ingest tab → upload → indexed confirmation

### Phase 4 — Retrieval + reranker + simple chat (2-3 days)
- `src/retrieval/hybrid_search.py`
- `src/retrieval/reranker.py`
- `src/synthesis/response.py`
- `src/ui/chat_ui.py` — basic chat with citations
- Build initial golden set (~20 Q&A)
- First Ragas baseline

### Phase 5 — Adaptive router (3-4 days)
- `src/routing/adaptive_router.py`
- `src/routing/strategies.py`
- `src/tools/sql_tool.py` + sample postgres schema
- Demo dataset (e.g. seeded e-commerce SQL + policy PDFs)
- Expand golden set to 30-50 across all strategies

### Phase 6 — Eval, tracing, polish (2 days)
- `src/eval/ragas_runner.py` + HTML report
- Langfuse integration
- Cost tracker tab in UI
- README rewrite with demo gif/screenshots
- (Optional) MCP surface

### Phase 7 — Stretch goals
- C-RAG self-reflection loop
- Multi-hop retrieval (when `clarify` strategy escalates)
- Expose as MCP server for Cursor/Claude Desktop
- Web search fallback when context insufficient

**Total realistic timeline:** 2-3 weeks of focused evening/weekend work.

---

## 14. Decision Log

| Decision | Chosen | Rejected | Reason |
|---|---|---|---|
| Routing layer | Query-time LLM classifier | Ingest-time extension matching | A PDF can have prose AND tables; routing must see the question |
| Doc parser | Docling | LangChain native loaders, LlamaParse, Marker | Free, local, table-aware, multi-format, already in deps |
| OCR | Qwen3-VL-Plus (API) | GLM-OCR (self-hosted), EasyOCR | No GPU needed, better quality on complex layouts, cheap per-image |
| Vector DB | Qdrant | pgvector, Weaviate, Chroma | Best hybrid (dense + sparse) support, already pinned |
| Sparse | BM25 via FastEmbed | SPLADE, no sparse | Free, fast, no GPU |
| Reranker | BGE-reranker-v2-m3 (local) | Cohere Rerank, ColBERT | Free, local, multilingual, ~80M params runs on CPU |
| LLM router | gpt-4.1-nano OR qwen-turbo | gpt-4.1, claude | Cheap, fast, classification doesn't need frontier |
| Tool protocol | Native function calling | MCP for everything | MCP only when external clients consume; one-agent app doesn't need it |
| Task queue | `BackgroundTasks` | Celery + Redis | YAGNI — add when measured queue depth justifies |
| File watching | Manual upload | watchdog filesystem watcher | UI-driven flow is enough; watcher is feature creep |
| DB sync | Live SQL tool | CDC (Debezium) | Core principle: never embed structured data |
| Eval | Ragas + custom router metric | None / vibes-based | Portfolio projects without metrics look unfinished |
| Tracing | Langfuse | Prometheus + Grafana + Jaeger | LLM-native, single signup, free tier |

---

## 15. Open Questions

1. **Embedding model** — start with `text-embedding-3-small` for cost, or jump to `BAAI/bge-m3` (free, multilingual, includes sparse natively, would let us drop FastEmbed)?
2. **Reranker model** — local BGE (free, +CPU) or Cohere (paid, faster, slightly better)?
3. **SQL demo source** — synthetic e-commerce dataset, or hook up to Neon (already in MCP list) for a real Postgres? Neon makes the demo more impressive.
4. **Multi-collection** — single `adaptive_rag` collection with metadata filters, or split per-domain (`policies`, `finance_reports`, etc.)? Metadata is simpler; per-domain enables faster filters at scale.
5. **Image-in-markdown** — Docling can extract images and embed as `![alt](path)`. Should we OCR those embedded images with Qwen and inline the text, or leave as references? Affects retrieval recall on visual content.
6. **Streaming** — Gradio supports streaming; worth wiring through synthesis layer for better UX.

Decisions on these can wait until Phase 4-5 measurement.

---

**End of architecture document.**
