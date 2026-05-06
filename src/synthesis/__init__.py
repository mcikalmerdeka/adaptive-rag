"""LLM synthesis layer.

Turns a query + ranked retrieval into a grounded answer with citations.
"""

from .response import (
    AnswerResponse,
    Citation,
    GroundedAnswerer,
    SynthesisError,
)

__all__ = [
    "AnswerResponse",
    "Citation",
    "GroundedAnswerer",
    "SynthesisError",
]
