"""Admin page — Langfuse cost / usage dashboard.

Pulls daily metrics from Langfuse and renders a few markdown tables.
Renders an empty-state with setup hints when keys aren't configured.
"""

from __future__ import annotations

import logging

import gradio as gr

from src.observability import CostSummary, fetch_cost_summary
from src.observability.langfuse_client import is_langfuse_enabled

logger = logging.getLogger(__name__)


_DAY_OPTIONS = [("Last 24 hours", 1), ("Last 7 days", 7), ("Last 30 days", 30)]


def _format_summary(summary: CostSummary) -> str:
    if not summary.enabled:
        return (
            "### Langfuse not configured\n\n"
            "Set `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` in your "
            "`.env`, restart the app, then come back here.\n\n"
            f"_Reason: {summary.error}_"
        )
    if summary.total_observations == 0:
        return (
            f"### No activity in window {summary.from_day} \u2192 {summary.to_day}\n\n"
            "Run a few chat questions in the **Chat** page and refresh."
        )
    return (
        f"### Window: {summary.from_day} \u2192 {summary.to_day}\n\n"
        f"- **Traces:** {summary.total_traces:,}\n"
        f"- **Observations:** {summary.total_observations:,}\n"
        f"- **Tokens:** {summary.total_tokens:,} "
        f"(in {summary.total_input_tokens:,} / out {summary.total_output_tokens:,})\n"
        f"- **Cost:** ${summary.total_cost_usd:.4f}\n"
    )


def _format_models(summary: CostSummary) -> str:
    if not summary.enabled or not summary.by_model:
        return ""
    rows = sorted(summary.by_model.values(), key=lambda u: u.cost_usd, reverse=True)
    lines = [
        "### By model",
        "",
        "| Model | Calls | In tokens | Out tokens | Cost (USD) |",
        "|-------|------:|----------:|-----------:|-----------:|",
    ]
    for u in rows:
        lines.append(
            f"| `{u.model}` | {u.observation_count:,} | {u.input_tokens:,} "
            f"| {u.output_tokens:,} | ${u.cost_usd:.4f} |"
        )
    return "\n".join(lines)


def _format_daily(summary: CostSummary) -> str:
    if not summary.enabled or not summary.daily:
        return ""
    lines = [
        "### By day",
        "",
        "| Day | Traces | Observations | Cost (USD) |",
        "|-----|-------:|-------------:|-----------:|",
    ]
    for d in summary.daily:
        lines.append(
            f"| {d.day} | {d.trace_count:,} | {d.observation_count:,} "
            f"| ${d.total_cost_usd:.4f} |"
        )
    return "\n".join(lines)


def _format_schema(sql_tool: object | None) -> str:
    """Render the SQL schema browser markdown.

    Takes the dispatcher's ``SqlTool`` (or ``None`` when SQL isn't
    configured) and introspects live — the tool returns an ``{"error": ...}``
    dict instead of raising when the database can't be reached.
    """
    if sql_tool is None:
        return (
            "### SQL database not configured\n\n"
            "Set `SQL_DATABASE_URL` in your environment (a read-only "
            "connection string) and restart the app to browse its schema."
        )
    try:
        schema = sql_tool.describe_schema()
    except Exception as exc:  # noqa: BLE001
        logger.exception("Schema introspection failed")
        return f"### Failed to read schema\n\n```\n{exc}\n```"

    if "error" in schema:
        return f"### Failed to read schema\n\n```\n{schema['error']}\n```"

    db_name = schema.get("database") or "(unknown)"
    tables = schema.get("tables") or []
    if not tables:
        return f"### Database: `{db_name}`\n\n_No tables found in the `public` schema._"

    lines: list[str] = [f"### Database: `{db_name}`", ""]
    for table in tables:
        lines.append(f"**{table['name']}**")
        lines.append("")
        lines.append("| Column | Type | Nullable |")
        lines.append("|--------|------|----------|")
        for col in table["columns"]:
            nullable = "YES" if col["nullable"] else "NO"
            lines.append(f"| `{col['name']}` | {col['type']} | {nullable} |")
        lines.append("")
    return "\n".join(lines)


def _refresh(window_days: int) -> tuple[str, str, str]:
    try:
        summary = fetch_cost_summary(days=int(window_days))
    except Exception as exc:  # noqa: BLE001
        logger.exception("Cost summary refresh failed")
        return (
            f"### Failed to load metrics\n\n```\n{exc}\n```",
            "",
            "",
        )
    return (
        _format_summary(summary),
        _format_models(summary),
        _format_daily(summary),
    )


def render_admin_page() -> None:
    """Render the Admin / Costs page."""
    enabled = is_langfuse_enabled()

    gr.Markdown(
        """
        ## Costs & Usage

        Live numbers pulled from Langfuse via the
        [public daily-metrics API](https://langfuse.com/docs/api). Token counts
        and USD costs come from the LLM token usage that LangChain records on
        every call \u2014 no separate price table here.
        """
    )

    if not enabled:
        gr.Markdown(
            "**Tracing is currently disabled.** Add your Langfuse keys to "
            "`.env` to start collecting traces and costs:\n\n"
            "```env\n"
            "LANGFUSE_PUBLIC_KEY=pk-lf-...\n"
            "LANGFUSE_SECRET_KEY=sk-lf-...\n"
            "LANGFUSE_HOST=https://cloud.langfuse.com\n"
            "```"
        )

    with gr.Row():
        window = gr.Dropdown(
            choices=_DAY_OPTIONS,
            value=7,
            label="Window",
            interactive=True,
            scale=2,
        )
        refresh_btn = gr.Button("Refresh", variant="primary", scale=1)

    summary_md = gr.Markdown(value="_Click **Refresh** to load metrics._")
    by_model_md = gr.Markdown()
    by_day_md = gr.Markdown()

    refresh_btn.click(
        fn=_refresh,
        inputs=[window],
        outputs=[summary_md, by_model_md, by_day_md],
    )

    # ---- SQL database browser -----------------------------------------
    gr.Markdown(
        """
        ## SQL database

        Tables and columns of the connected database — the same schema the
        `sql_only` / `hybrid` strategies query. Read-only introspection,
        nothing is cached.
        """
    )
    schema_refresh_btn = gr.Button("Refresh schema", variant="primary")
    schema_md = gr.Markdown(value="_Click **Refresh schema** to inspect the database._")

    def _refresh_schema() -> str:
        from src.ui.chat_ui import _get_dispatcher

        return _format_schema(_get_dispatcher().sql)

    schema_refresh_btn.click(fn=_refresh_schema, outputs=[schema_md])
