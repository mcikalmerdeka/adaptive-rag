"""LLM synthesis layer.

Turns a query + ranked retrieval (and optionally SQL data) into a grounded
answer with inline citations.
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
