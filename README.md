# AdaptiveRAG

**Hybrid Adaptive RAG with query-time strategy selection, markdown-first ingestion, and an optional MCP tool surface.**

This project intelligently routes data and queries: documents go to a hybrid (dense + sparse) vector store, structured data is queried live via tools, and the LLM picks the right strategy *per query* — not per file extension.

> Phased build. We're at **Phase 3** — full convert → chunk → hybrid index in Qdrant. Adaptive query routing comes in Phase 5.

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

- **Embedding cache** via LangChain's `CacheBackedEmbeddings` + `LocalFileStore` — every text+model combination is cached on disk.
- **Library view** in the UI — table of all indexed docs with a delete-by-doc-id action.
- **Two backends, zero config:** if `QDRANT_URL` is set we connect to a remote/Docker/Cloud Qdrant; otherwise we run embedded out of `./qdrant_storage/`.

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
    ├── cache/
    │   ├── ocr_cache.py            # SHA256 disk cache for OCR markdown
    │   └── embedding_cache.py      # CacheBackedEmbeddings wrapper
    ├── utils/
    │   └── pdf_inspector.py        # born-digital heuristic + page rendering
    └── ui/
        ├── main_ui.py              # Tab composition
        ├── markdown_converter_ui.py # Convert tab
        └── ingest_ui.py            # Ingest tab
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

**Convert tab** — single-document preview; pick a file, optionally force Qwen for PDFs, see the markdown and download.

**Ingest tab** — multi-file ingestion. Each file is converted → chunked → upserted into Qdrant. The library on the right shows what's currently indexed and lets you delete by `doc_id`. Re-ingesting a file by default replaces its previous chunks; tick **Skip if already indexed** to no-op instead.

## Roadmap

- ✅ Phase 1: Docling baseline document conversion
- ✅ Phase 2: Parser router (Docling + Qwen3-VL fallback) with caching
- ✅ Phase 3: Header-aware chunking + hybrid (dense + BM25) Qdrant indexing
- ⬜ Phase 4: Hybrid retrieval (RRF fusion) + reranker + basic RAG chat
- ⬜ Phase 5: **Adaptive query router** — `no_retrieval` / `vector_only` / `sql_only` / `hybrid` / `clarify` per query
- ⬜ Phase 6: Ragas evaluation, Langfuse tracing, cost tracker
- ⏸️ Phase 7: C-RAG self-reflection, MCP server surface, web fallback

Full plan in `PROJECT_PLAN.md`.

## License

MIT
