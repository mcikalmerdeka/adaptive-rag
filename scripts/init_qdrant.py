"""Initialize the Qdrant collection for AdaptiveRAG.

Useful when bootstrapping a fresh Qdrant deployment (Docker / Cloud) before
running the app, or to verify your env vars are wired correctly.

Usage:
    uv run python scripts/init_qdrant.py
    uv run python scripts/init_qdrant.py --recreate
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Allow running this script directly from the repo root.
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv  # noqa: E402

from src.indexing import QdrantStore  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("init_qdrant")


def main() -> int:
    parser = argparse.ArgumentParser(description="Initialize Qdrant collection.")
    parser.add_argument(
        "--recreate",
        action="store_true",
        help="Drop the existing collection (if any) before creating.",
    )
    args = parser.parse_args()

    load_dotenv()

    store = QdrantStore()

    if args.recreate:
        try:
            store.client.delete_collection(store.collection_name)
            logger.info(f"Dropped collection '{store.collection_name}'")
        except Exception as exc:
            logger.warning(f"Drop failed (it may not exist yet): {exc}")
        # Re-init to recreate.
        store = QdrantStore()

    total = store.total_chunks()
    logger.info(
        f"Collection '{store.collection_name}' is ready "
        f"({total} existing chunks)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
