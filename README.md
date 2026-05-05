# AdaptiveRAG

**Hybrid Adaptive RAG with query-time strategy selection, markdown-first ingestion, and an optional MCP tool surface.**

This project intelligently routes data and queries: documents go to a vector store, structured data is queried live via tools, and the LLM picks the right strategy *per query* — not per file extension.

> Heads up: this is a phased build. Right now we're at **Phase 2** — solid document → markdown conversion with smart parser routing. Vector indexing, retrieval, and the adaptive query router come next.

See:
- `ARCHITECTURE.md` — full system design and rationale
- `PROJECT_PLAN.md` — phase-by-phase checklist with progress

---

## Phase 2 — Document → Markdown ingestion (current)

What works today:

- **Multi-format input:** `.pdf`, `.docx`, `.pptx`, `.xlsx`, `.html` / `.htm`, `.md`, `.txt`, `.csv`, `.png`, `.jpg` / `.jpeg`, `.webp`
- **Smart parser routing:**

  | Input | Parser | Why |
  |---|---|---|
  | `.md`, `.txt` | passthrough | already markdown / plain text |
  | `.png`, `.jpg`, `.webp` | Qwen3-VL | vision model beats local OCR |
  | `.pdf` (born-digital) | Docling | fast, free, lossless |
  | `.pdf` (scanned) | Qwen3-VL per page | better than EasyOCR on layouts |
  | `.docx`, `.pptx`, `.xlsx`, `.html`, `.csv` | Docling | native structural parsing |

- **Born-digital vs scanned heuristic:** PDFs with <150 chars of extractable text in the first 3 pages are treated as scanned and routed to Qwen.
- **Disk cache:** OCR results are SHA256-keyed in `.cache/ocr/`. Re-uploading the same file (or re-OCR'ing the same page) returns instantly without an API call.
- **Override:** UI checkbox forces Qwen on PDFs when you know OCR quality matters.
- **Progress:** multi-page scanned PDFs report per-page progress.
- **Retry:** Qwen calls retry with exponential backoff on rate limit / network errors.

## Project structure

```
adaptive-rag/
├── app.py                          # Gradio entry
├── ARCHITECTURE.md
├── PROJECT_PLAN.md
├── .env.example
├── pyproject.toml
├── requirements.txt
└── src/
    ├── core/
    │   ├── file_detector.py        # extension/MIME → DocumentFormat
    │   ├── docling_parser.py       # Docling wrapper
    │   ├── qwen_parser.py          # Qwen3-VL OCR + retry
    │   ├── parser_router.py        # picks parser per file
    │   └── converter.py            # public API used by UI
    ├── utils/
    │   └── pdf_inspector.py        # born-digital heuristic + page rendering
    ├── cache/
    │   └── ocr_cache.py            # SHA256 disk cache for OCR results
    └── ui/
        └── markdown_converter_ui.py
```

## Setup

```bash
# 1. Install dependencies (uv recommended)
uv sync

# 2. Copy and fill in your API keys
cp .env.example .env
# edit .env and set OPENAI_API_KEY and QWEN_API_KEY

# 3. Run the app
uv run app.py
```

Open `http://localhost:7860`.

> First run downloads Docling models (~1-2 GB). Subsequent runs use the local cache.

## API keys

| Variable | Used for | Get it at |
|---|---|---|
| `QWEN_API_KEY` | Image + scanned PDF OCR via Qwen3-VL | https://dashscope.aliyun.com/ |
| `OPENAI_API_KEY` | Embeddings + LLM (later phases) | https://platform.openai.com/ |

If `QWEN_API_KEY` is missing, the UI still runs — but uploading an image or scanned PDF will fail. Born-digital documents work fine without it.

## Running

```bash
uv run app.py
```

The Gradio interface lets you:

1. Upload a file
2. Optionally tick "Force Qwen3-VL OCR for PDFs"
3. Click **Convert to Markdown**
4. See the parser used (`docling` / `qwen3-vl` / `passthrough`) in the status
5. Preview and download the `.md`

## Roadmap

This phase finishes once we can ingest each supported format reliably. Next up:

- **Phase 3:** header-aware chunking + hybrid (dense + BM25) Qdrant indexing
- **Phase 4:** retrieval with reranker, basic RAG chat
- **Phase 5:** the actual *adaptive* router — query-time strategy selection across `no_retrieval` / `vector_only` / `sql_only` / `hybrid` / `clarify`
- **Phase 6:** Ragas evaluation, Langfuse tracing, cost tracking

Full plan in `PROJECT_PLAN.md`.

## License

MIT
