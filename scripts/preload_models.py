"""Pre-download models during Docker build to avoid cold-start penalty.

Called by the Dockerfile builder stage. This is separate from the main app
so it can be run once at build time and the downloaded caches get copied
into the final image.
"""

import logging

logging.basicConfig(level=logging.INFO)

# Trigger Docling model download. warm_up() initializes the PDF pipeline,
# which is what actually fetches the layout + TableFormer models — merely
# constructing MarkdownConverterService() does NOT (verified: docling's
# DocumentConverter.__init__ never calls initialize_pipeline).
print("Pre-downloading Docling models...")
from src.core.docling_parser import DoclingParser  # noqa: E402

DoclingParser().warm_up()
print("Docling models cached.")

# Trigger FlashRank model download
print("Pre-downloading FlashRank model...")
from src.retrieval.reranker import Reranker  # noqa: E402

Reranker()
print("FlashRank model cached.")

# Trigger FastEmbed BM25 tokenizer download
print("Pre-downloading FastEmbed BM25 tokenizer...")
from fastembed import SparseTextEmbedding  # noqa: E402

SparseTextEmbedding(model_name="Qdrant/bm25")
print("FastEmbed tokenizer cached.")
