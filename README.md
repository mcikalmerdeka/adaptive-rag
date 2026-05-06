# AdaptiveRAG

**Hybrid Adaptive RAG with query-time strategy selection, markdown-first ingestion, and an optional MCP tool surface.**

This project intelligently routes data and queries: documents go to a hybrid (dense + sparse) vector store, structured data is queried live via tools, and the LLM picks the right strategy *per query* — not per file extension.

> Phased build. We're at **Phase 4** — full convert → chunk → hybrid index → retrieve → rerank → grounded chat. Adaptive query routing comes in Phase 5.

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
- **All knobs in one place:** `src/config/settings.py` is the single source of truth. Override via `.env`:
  - `RERANK_TOP_K=5` (final chunks shown to the LLM, default `5`)
  - `RETRIEVAL_PREFETCH_K=25` (candidates fetched before reranking)
  - `RERANKER_MODEL` (swap to `ms-marco-TinyBERT-L-2-v2` for speed or `rank-T5-flan` for quality)
  - `LLM_MODEL`, `LLM_TEMPERATURE`, `LLM_MAX_TOKENS`
  - `DENSE_MODEL`, `SPARSE_MODEL`, `CHUNK_SIZE`, `CHUNK_OVERLAP`, etc.

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
    ├── synthesis/                  # Chunks → grounded answer + citations
    │   └── response.py             # GroundedAnswerer (ChatOpenAI)
    ├── cache/
    │   ├── ocr_cache.py            # SHA256 disk cache for OCR markdown
    │   └── embedding_cache.py      # SHA256 disk cache for embeddings
    ├── utils/
    │   └── pdf_inspector.py        # born-digital heuristic + page rendering
    └── ui/
        ├── main_ui.py              # Tab composition
        ├── chat_ui.py              # Chat tab
        ├── ingest_ui.py            # Ingest tab
        └── markdown_converter_ui.py # Convert tab
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

# 4. Run the app
uv run app.py
```

Open `http://localhost:7860`.

> First run downloads Docling (~1-2 GB) and FastEmbed BM25 tokenizer (~few MB).

## API keys

| Variable | Used for | Get it at |
|---|---|---|
| `OPENAI_API_KEY` | Dense embeddings (and LLM later) | https://platform.openai.com/ |
| `QWEN_API_KEY` | Image + scanned PDF OCR via Qwen3-VL | https://dashscope.aliyun.com/ |
| `QDRANT_URL` (optional) | Connect to a remote Qdrant. Leave unset for embedded mode. | — |
| `QDRANT_API_KEY` (optional) | Qdrant Cloud auth | https://cloud.qdrant.io/ |
| `QDRANT_PATH` (optional) | Override the embedded storage directory | — |
| `QDRANT_COLLECTION` (optional) | Override the default collection name (`adaptive_rag`) | — |

## Using the app

**Chat tab** — ask questions about your indexed documents. Each turn runs hybrid retrieval (dense + BM25 + RRF), reranks the top `RETRIEVAL_PREFETCH_K` candidates with a cross-encoder, and the LLM answers grounded in the top `RERANK_TOP_K` chunks (default 5). Inline `[n]` citations appear in the answer; the **Sources** panel on the right shows which chunks the LLM actually cited, with rerank scores. The footer line shows model + per-turn timings.

**Ingest tab** — multi-file ingestion. Each file is converted → chunked → upserted into Qdrant. The library on the right shows what's currently indexed and lets you delete by `doc_id`. Re-ingesting a file by default replaces its previous chunks; tick **Skip if already indexed** to no-op instead.

**Convert tab** — single-document preview; pick a file, optionally force Qwen for PDFs, see the markdown and download.

## Roadmap

- ✅ Phase 1: Docling baseline document conversion
- ✅ Phase 2: Parser router (Docling + Qwen3-VL fallback) with caching
- ✅ Phase 3: Header-aware chunking + hybrid (dense + BM25) Qdrant indexing
- ✅ Phase 4: Hybrid retrieval + FlashRank reranker + grounded chat with citations
- ⬜ Phase 5: **Adaptive query router** — `no_retrieval` / `vector_only` / `sql_only` / `hybrid` / `clarify` per query
- ⬜ Phase 6: Ragas evaluation, Langfuse tracing, cost tracker
- ⏸️ Phase 7: C-RAG self-reflection, MCP server surface, web fallback

Full plan in `PROJECT_PLAN.md`.

## License

MIT
