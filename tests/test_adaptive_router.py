"""Tests for src.routing.adaptive_router — model / reasoning-effort wiring."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import src.routing.adaptive_router as router_module
from src.routing.adaptive_router import AdaptiveRouter
from src.routing.dispatcher import AdaptiveDispatcher
from src.tools.sql_tool import SqlTool


def _fake_settings(**overrides: object) -> SimpleNamespace:
    """Settings stand-in exposing only what AdaptiveRouter reads."""
    values: dict[str, object] = {
        "ROUTER_MODEL": "gpt-6-luna",
        "ROUTER_TEMPERATURE": 0.0,
        "ROUTER_REASONING_EFFORT": "none",
    }
    values.update(overrides)
    # Mirror the Settings.router_reasoning / router_temperature properties.
    effort = values["ROUTER_REASONING_EFFORT"]
    values["router_reasoning"] = (
        None if effort in (None, "", "off") else {"effort": effort}
    )
    values["router_temperature"] = (
        None if effort not in (None, "", "off", "none")
        else values["ROUTER_TEMPERATURE"]
    )
    return SimpleNamespace(**values)


def _router(monkeypatch: pytest.MonkeyPatch, **overrides: object) -> AdaptiveRouter:
    monkeypatch.setattr(
        router_module, "settings", _fake_settings(**overrides), raising=False
    )
    return AdaptiveRouter(sql_available=False)


class TestRouterModelWiring:
    """The router client must carry the configured model + reasoning effort."""

    def test_uses_configured_model_and_reasoning_effort(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        router = _router(monkeypatch)
        assert router._llm.model_name == "gpt-6-luna"
        assert router._llm.reasoning == {"effort": "none"}

    def test_structured_output_is_bound_on_top_of_the_base_model(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        router = _router(monkeypatch)
        assert router._decision_llm is not None
        assert router._decision_llm is not router._llm

    def test_effort_off_omits_the_reasoning_parameter(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        router = _router(monkeypatch, ROUTER_REASONING_EFFORT="off")
        assert router._llm.reasoning is None

    def test_temperature_kept_at_effort_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        router = _router(monkeypatch)
        assert router._llm.temperature == 0.0

    def test_temperature_omitted_when_effort_raised(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # gpt-6-luna 400s on `temperature` at any effort other than none.
        router = _router(
            monkeypatch,
            ROUTER_REASONING_EFFORT="high",
            router_reasoning={"effort": "high"},
        )
        assert router._llm.temperature is None


class TestDispatcherSqlAccessor:
    """``AdaptiveDispatcher.sql`` hands the Admin UI the lazy-built tool."""

    def test_sql_none_when_disabled(self) -> None:
        dispatcher = AdaptiveDispatcher(sql_tool=False)
        assert dispatcher.sql is None

    def test_sql_returns_injected_tool(self) -> None:
        # ``sql_tool`` overrides must be real SqlTool instances (isinstance
        # check in __init__), so build one without running __init__.
        tool = SqlTool.__new__(SqlTool)
        dispatcher = AdaptiveDispatcher(sql_tool=tool)
        assert dispatcher.sql is tool
