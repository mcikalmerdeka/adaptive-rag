"""Top-level Gradio app: left sidebar navigation over page columns.

Each page renders into a ``gr.Column``; the sidebar's stacked nav
buttons toggle page visibility (the documented Gradio sidebar-navigation
pattern). The active page's button is highlighted via ``variant``.
Component state survives page switches, matching the old tab behavior.

Gradio 6 takes page CSS at launch time, not in the Blocks constructor:
``app.py`` passes ``NAV_CSS`` to ``launch(css=...)``.
"""

from __future__ import annotations

import gradio as gr
from dotenv import load_dotenv

from .admin_ui import render_admin_page
from .chat_ui import render_chat_page
from .ingest_ui import render_ingest_page
from .markdown_converter_ui import render_convert_page

load_dotenv()

PAGES = ["Chat", "Ingest", "Convert", "Admin"]

# Makes inactive nav items read as sidebar links instead of chunky
# buttons; the active item keeps the filled primary variant.
NAV_CSS = """
.sidebar-nav button.secondary {
    background: transparent;
    border: none;
    box-shadow: none;
    justify-content: flex-start;
    text-align: left;
}
.sidebar-nav button.primary {
    justify-content: flex-start;
    text-align: left;
}
"""


def _select_page(selection: str | None) -> list[dict]:
    """Return a flat update list matching the nav event's ``outputs``.

    Order: one visibility update per page (PAGES order), then one
    variant update per nav button (PAGES order) — 2 * len(PAGES)
    values, exactly as ``outputs=[pages] + nav_buttons`` expects.
    Gradio zips the return 1:1 against that flat list, so it must not
    be nested.

    Unknown or missing selections fall back to the first page so the
    app never renders a blank main area.
    """
    if selection not in PAGES:
        selection = PAGES[0]
    page_updates = [gr.update(visible=selection == name) for name in PAGES]
    nav_updates = [
        gr.update(variant="primary" if selection == name else "secondary")
        for name in PAGES
    ]
    return page_updates + nav_updates


def build_app() -> gr.Blocks:
    with gr.Blocks(title="AdaptiveRAG") as demo:
        with gr.Sidebar(position="left"):
            gr.Markdown("## AdaptiveRAG")
            nav_buttons = [
                gr.Button(
                    name,
                    variant="primary" if name == PAGES[0] else "secondary",
                    elem_classes=["sidebar-nav"],
                )
                for name in PAGES
            ]

        with gr.Column(visible=True) as chat_page:
            render_chat_page()
        with gr.Column(visible=False) as ingest_page:
            render_ingest_page()
        with gr.Column(visible=False) as convert_page:
            render_convert_page()
        with gr.Column(visible=False) as admin_page:
            render_admin_page()

        gr.Markdown(
            """
            ---
            Powered by [MarkItDown](https://github.com/microsoft/markitdown),
            [GLM-5.3-Flash](https://docs.z.ai/guides/vlm/glm-5.3-flash),
            [Qdrant](https://qdrant.tech/) and
            [LangChain](https://python.langchain.com/) ·
            Built with [Gradio](https://gradio.app)
            """
        )

        for name, btn in zip(PAGES, nav_buttons, strict=True):
            btn.click(
                fn=lambda target=name: _select_page(target),
                inputs=None,
                outputs=[chat_page, ingest_page, convert_page, admin_page]
                + nav_buttons,
            )

    return demo
