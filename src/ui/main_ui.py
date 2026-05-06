"""Top-level Gradio app composing all tabs."""

from __future__ import annotations

import gradio as gr
from dotenv import load_dotenv

from .ingest_ui import render_ingest_tab
from .markdown_converter_ui import render_convert_tab

load_dotenv()


def build_app() -> gr.Blocks:
    with gr.Blocks(title="AdaptiveRAG") as demo:
        gr.Markdown(
            """
            # AdaptiveRAG

            **Hybrid Adaptive RAG with markdown-first ingestion and
            query-time strategy selection.** This UI exposes the ingestion
            pipeline. Adaptive query routing arrives in a later phase.
            """
        )

        with gr.Tabs():
            with gr.Tab("Convert"):
                render_convert_tab()
            with gr.Tab("Ingest"):
                render_ingest_tab()

        gr.Markdown(
            """
            ---
            Powered by [Docling](https://github.com/docling-project/docling),
            [Qwen3-VL](https://help.aliyun.com/zh/dashscope/),
            [Qdrant](https://qdrant.tech/) and
            [LangChain](https://python.langchain.com/) ·
            Built with [Gradio](https://gradio.app)
            """
        )

    return demo
