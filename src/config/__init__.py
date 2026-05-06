"""Central configuration for AdaptiveRAG.

All user-tunable knobs live in :mod:`src.config.settings`. Import the
``settings`` object from there:

    from src.config import settings
    print(settings.RERANK_TOP_K)

To override any value, set the matching env var in ``.env`` (e.g.
``RERANK_TOP_K=8``). Internal constants that are *not* user-facing (e.g.
the dense vector field name) stay where they're used.
"""

from .settings import settings

__all__ = ["settings"]
