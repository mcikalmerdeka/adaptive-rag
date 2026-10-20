"""Tests for src.ui.main_ui — sidebar page navigation.

``_select_page`` returns a FLAT update list matching the event's
``outputs=[page columns] + nav_buttons`` wiring: one visibility update
per page (in PAGES order), then one variant update per nav button. A
nested return passes a naive unit test but fails Gradio's postprocess
validation ("needed: 8, returned: 2") — hence the shape assertions.
Unknown selections fall back to the first page. The full Blocks app
must build — layout plus event wiring — without launching a server.
"""

from __future__ import annotations

import gradio as gr

from src.ui.main_ui import PAGES, _select_page, build_app


class TestSelectPage:
    """Flat update list: page visibility first, then nav highlights."""

    def test_returns_flat_list_matching_outputs_count(self) -> None:
        updates = _select_page("Ingest")

        assert isinstance(updates, list)
        assert len(updates) == 2 * len(PAGES)

    def test_shows_only_selected_page(self) -> None:
        updates = _select_page("Ingest")

        flags = [u["visible"] for u in updates[: len(PAGES)]]
        assert flags == [False, True, False, False]

    def test_highlights_only_selected_nav_button(self) -> None:
        updates = _select_page("Ingest")

        variants = [u["variant"] for u in updates[len(PAGES) :]]
        assert variants == ["secondary", "primary", "secondary", "secondary"]

    def test_every_page_selection_yields_one_visible_page(self) -> None:
        n = len(PAGES)
        for i, page in enumerate(PAGES):
            updates = _select_page(page)
            flags = [u["visible"] for u in updates[:n]]
            variants = [u["variant"] for u in updates[n:]]
            assert flags == [page == name for name in PAGES]
            assert variants == [
                "primary" if page == name else "secondary" for name in PAGES
            ]

    def test_unknown_selection_falls_back_to_first_page(self) -> None:
        assert _select_page(None) == _select_page(PAGES[0])
        assert _select_page("nope") == _select_page(PAGES[0])


class TestBuildApp:
    """``build_app`` assembles the sidebar layout and its events."""

    def test_builds_blocks_with_exactly_one_sidebar(self) -> None:
        demo = build_app()

        assert isinstance(demo, gr.Blocks)
        sidebars = [b for b in demo.blocks.values() if isinstance(b, gr.Sidebar)]
        assert len(sidebars) == 1
