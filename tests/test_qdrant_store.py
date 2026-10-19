"""Tests for src.indexing.qdrant_store — client wiring, mocked QdrantClient, no network."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import src.indexing.qdrant_store as qdrant_store_module
from src.indexing.qdrant_store import QdrantStore


def _fake_settings(**overrides):
    """Replace the module-level settings handle for full test control."""
    base = dict(
        QDRANT_URL=None,
        QDRANT_API_KEY=None,
        QDRANT_PATH="./qdrant_storage",
        QDRANT_COLLECTION="adaptive_rag",
        DENSE_SIZE=1536,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.fixture(autouse=True)
def _isolated_singleton():
    """QdrantStore caches one instance per connection — keep tests independent."""
    QdrantStore._instances.clear()
    yield
    QdrantStore._instances.clear()


def _stub_embeddings_and_store(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Stub embedding factories + QdrantVectorStore; return the client-ctor mock."""
    monkeypatch.setattr(
        qdrant_store_module, "build_dense_embeddings", MagicMock(return_value=MagicMock())
    )
    monkeypatch.setattr(
        qdrant_store_module, "build_sparse_embeddings", MagicMock(return_value=MagicMock())
    )
    monkeypatch.setattr(qdrant_store_module, "QdrantVectorStore", MagicMock())
    return MagicMock(return_value=MagicMock())


class TestClientWiring:
    """QdrantClient construction for the remote (Docker/Cloud) and embedded backends."""

    def test_remote_client_gets_explicit_timeout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Remote connections must pass an explicit request timeout.

        qdrant-client defaults to 5s, which is too tight for WAN round-trips
        against Qdrant Cloud — large upserts would fail spuriously.
        """
        monkeypatch.setattr(qdrant_store_module, "settings", _fake_settings())
        client_ctor = _stub_embeddings_and_store(monkeypatch)
        monkeypatch.setattr(qdrant_store_module, "QdrantClient", client_ctor)

        QdrantStore(url="https://example.cloud.qdrant.io", api_key="secret")

        client_ctor.assert_called_once()
        kwargs = client_ctor.call_args.kwargs
        assert kwargs["url"] == "https://example.cloud.qdrant.io"
        assert kwargs["api_key"] == "secret"
        assert "timeout" in kwargs, "remote QdrantClient must pass an explicit timeout"
        assert kwargs["timeout"] >= 30

    def test_embedded_client_uses_local_path(self, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
        """No URL → embedded mode bound to the storage directory (timeout not a kwarg)."""
        monkeypatch.setattr(
            qdrant_store_module,
            "settings",
            _fake_settings(QDRANT_PATH=str(tmp_path)),
        )
        client_ctor = _stub_embeddings_and_store(monkeypatch)
        monkeypatch.setattr(qdrant_store_module, "QdrantClient", client_ctor)

        QdrantStore()

        client_ctor.assert_called_once_with(path=str(tmp_path))
