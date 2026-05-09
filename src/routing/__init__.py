"""Adaptive query router.

The router classifies each incoming question into one of five execution
strategies, then the dispatcher runs that strategy. This is what makes
the project actually "Adaptive RAG" (per Jeong et al., 2024) rather than
static dispatch on file extensions.
"""

from .adaptive_router import AdaptiveRouter, RouterDecision
from .dispatcher import (
    AdaptiveAnswer,
    AdaptiveDispatcher,
    DispatchError,
)
from .strategies import Strategy

__all__ = [
    "AdaptiveAnswer",
    "AdaptiveDispatcher",
    "AdaptiveRouter",
    "DispatchError",
    "RouterDecision",
    "Strategy",
]
