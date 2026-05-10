"""Langfuse v4 wrapper.

Three jobs:

1. **Lazy singleton** — first call to :func:`get_langfuse` initializes the
   client from env vars. Subsequent calls return the same instance.
2. **No-op when disabled** — if either Langfuse key is missing, every
   helper returns a stub so call sites can stay clean (no
   ``if is_enabled:`` everywhere). The ``span`` context manager becomes a
   trivial passthrough; the LangChain callback list becomes empty.
3. **One spelling for spans** — everyone calls
   ``with span("retrieval.hybrid_search", input=...) as s:`` and we
   handle the disabled-mode branching internally.

We intentionally do NOT use ``from langfuse.openai import openai`` (the
auto-instrumented OpenAI shim) because we route LLM calls through
LangChain's ``ChatOpenAI`` — and the LangChain ``CallbackHandler``
already captures token counts, model, latency, etc. for those calls.
The Qwen OCR path uses the raw OpenAI SDK; if we want OCR traces later
we can wire that one call site to ``langfuse.openai`` separately.
"""

from __future__ import annotations

import contextlib
import logging
import os
from collections.abc import Iterator
from typing import Any

from src.config import settings

logger = logging.getLogger(__name__)


_client: Any = None  # langfuse.Langfuse | None
_callback_handler: Any = None  # langfuse.langchain.CallbackHandler | None
_init_attempted: bool = False


def is_langfuse_enabled() -> bool:
    """True when Langfuse keys are configured. Cheap, safe to call often."""
    return settings.langfuse_enabled


def get_langfuse() -> Any | None:
    """Return the singleton ``Langfuse`` client, or ``None`` if disabled.

    First call lazily reads env, exports them to the standard Langfuse
    variable names, and instantiates the client. Subsequent calls hit the
    cache.
    """
    global _client, _init_attempted
    if _client is not None or _init_attempted:
        return _client

    _init_attempted = True
    if not is_langfuse_enabled():
        logger.info(
            "Langfuse keys not set — tracing disabled. Set LANGFUSE_PUBLIC_KEY "
            "and LANGFUSE_SECRET_KEY in .env to enable."
        )
        return None

    # The Langfuse SDK reads these env vars itself, but we set them
    # explicitly so the rest of the app doesn't depend on .env loading
    # order.
    os.environ.setdefault("LANGFUSE_PUBLIC_KEY", settings.LANGFUSE_PUBLIC_KEY or "")
    os.environ.setdefault("LANGFUSE_SECRET_KEY", settings.LANGFUSE_SECRET_KEY or "")
    os.environ.setdefault("LANGFUSE_HOST", settings.LANGFUSE_HOST)

    try:
        from langfuse import get_client as _get_lf_client

        _client = _get_lf_client()
        logger.info(f"Langfuse tracing enabled (host={settings.LANGFUSE_HOST})")
    except Exception as exc:
        logger.warning(f"Langfuse init failed; continuing without tracing: {exc}")
        _client = None
    return _client


def get_callback_handler() -> list[Any]:
    """Return ``[CallbackHandler]`` for LangChain ``invoke(config={...})``.

    Returns an empty list when Langfuse is disabled — pass it directly to
    ``config={"callbacks": handlers}`` and you get tracing or no-op for
    free.
    """
    global _callback_handler
    client = get_langfuse()
    if client is None:
        return []

    if _callback_handler is None:
        try:
            from langfuse.langchain import CallbackHandler

            _callback_handler = CallbackHandler()
        except Exception as exc:
            logger.warning(f"Langfuse CallbackHandler init failed: {exc}")
            return []
    return [_callback_handler]


@contextlib.contextmanager
def span(
    name: str,
    *,
    input: Any = None,
    metadata: dict[str, Any] | None = None,
    as_type: str = "span",
) -> Iterator[Any]:
    """Context manager that opens a Langfuse observation, or no-ops.

    Yields the underlying span (call ``.update(output=..., metadata=...)``
    on it) when tracing is enabled, or a tiny stub with the same surface
    so call sites don't need ``if`` branches.
    """
    client = get_langfuse()
    if client is None:
        yield _NoopSpan()
        return

    try:
        with client.start_as_current_observation(
            as_type=as_type, name=name, input=input, metadata=metadata or {}
        ) as observation:
            yield observation
    except Exception as exc:
        # Tracing must never break the application. Log and continue.
        logger.warning(f"Langfuse span '{name}' failed: {exc}")
        yield _NoopSpan()


def flush_traces() -> None:
    """Flush queued events. Safe to call when disabled (no-op)."""
    client = get_langfuse()
    if client is None:
        return
    try:
        client.flush()
    except Exception as exc:
        logger.warning(f"Langfuse flush failed: {exc}")


class _NoopSpan:
    """Stand-in for a Langfuse span so call sites can use the same API."""

    def update(self, **_: Any) -> None:
        return None

    def update_trace(self, **_: Any) -> None:
        return None

    def score(self, **_: Any) -> None:
        return None

    def __getattr__(self, _: str) -> Any:
        return self.update
