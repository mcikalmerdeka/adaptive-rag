"""End-to-end DeepEval evaluation.

For every golden example whose expected strategy involves retrieval
(``vector_only`` or ``hybrid``), runs the dispatcher to produce an
answer + chunks, then scores it with DeepEval:

- ``FaithfulnessMetric``         — answer claims are grounded in context
- ``AnswerRelevancyMetric``      — answer addresses the question
- ``ContextualRelevancyMetric``  — retrieved chunks are relevant to the query

Output:

- ``src/eval/reports/deepeval_<timestamp>.json`` — raw scores per question
- ``src/eval/reports/deepeval_<timestamp>.html`` — quick visual summary

Usage:
    uv run python -m src.eval.run_deepeval
    uv run python -m src.eval.run_deepeval --limit 1   # cheapest: one row only

The bundled ``golden.jsonl`` is intentionally tiny (smoke set). Each
``vector_only`` / ``hybrid`` row drives a full dispatch + three metrics.
"""

from __future__ import annotations

import argparse
import html
import json
import logging
import sys
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.config import settings
from src.routing import AdaptiveDispatcher
from src.routing.strategies import Strategy

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("deepeval_eval")

DEFAULT_GOLDEN = Path("src/eval/golden.jsonl")
REPORTS_DIR = Path("src/eval/reports")

RETRIEVAL_STRATEGIES = {Strategy.VECTOR_ONLY.value, Strategy.HYBRID.value}


def load_golden(path: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw or raw.startswith("//"):
                continue
            out.append(json.loads(raw))
    return out


def collect_runs(
    examples: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Run the dispatcher and capture (query, answer, chunk texts) per row."""
    dispatcher = AdaptiveDispatcher()
    rows: list[dict[str, Any]] = []
    for ex in examples:
        if ex["expected_strategy"] not in RETRIEVAL_STRATEGIES:
            continue
        try:
            ans = dispatcher.answer(ex["query"])
        except Exception as exc:
            logger.warning(f"[{ex.get('id')}] dispatch failed: {exc}")
            continue
        chunks = [c.text for c in ans.chunks]
        if not chunks:
            logger.warning(f"[{ex.get('id')}] no chunks returned, skipping")
            continue
        rows.append(
            {
                "id": ex.get("id"),
                "query": ex["query"],
                "expected_strategy": ex["expected_strategy"],
                "actual_strategy": ans.strategy.value,
                "answer": ans.answer,
                "contexts": chunks,
            }
        )
        print(
            f"  [{ex.get('id'):<6}] {ans.strategy.value:<12} "
            f"chunks={len(chunks)} answer_len={len(ans.answer)}"
        )
    return rows


def run_deepeval(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Score rows with DeepEval metrics. Returns a list of result dicts."""
    if not rows:
        raise RuntimeError("No rows to evaluate.")

    from deepeval import evaluate
    from deepeval.metrics import (
        AnswerRelevancyMetric,
        ContextualRelevancyMetric,
        FaithfulnessMetric,
    )
    from deepeval.test_case import LLMTestCase

    test_cases: list[LLMTestCase] = []
    for row in rows:
        tc = LLMTestCase(
            input=row["query"],
            actual_output=row["answer"],
            retrieval_context=row["contexts"],
        )
        test_cases.append(tc)

    model = settings.LLM_MODEL

    faithfulness = FaithfulnessMetric(threshold=0.5, model=model)
    answer_relevancy = AnswerRelevancyMetric(threshold=0.5, model=model)
    contextual_relevancy = ContextualRelevancyMetric(threshold=0.5, model=model)

    metrics = [faithfulness, answer_relevancy, contextual_relevancy]

    eval_result = evaluate(
        test_cases=test_cases,
        metrics=metrics,
    )

    # Build structured results (test_results are 1:1 with test_cases)
    results: list[dict[str, Any]] = []
    for i, row in enumerate(rows):
        scores: dict[str, Any] = {
            "user_input": row["query"],
            "response": row["answer"],
        }
        if i < len(eval_result.test_results):
            tr = eval_result.test_results[i]
            if tr.metrics_data:
                for md in tr.metrics_data:
                    scores[md.name] = md.score
        results.append(scores)
    return results


def render_html(results: list[dict[str, Any]], *, ran_at: str, golden_path: Path) -> str:
    """Compact self-contained HTML report."""
    metric_cols = [
        c for c in results[0].keys()
        if c not in {"user_input", "response", "retrieved_contexts"}
    ] if results else []

    summary_rows = []
    for col in metric_cols:
        values = [r.get(col) for r in results if isinstance(r.get(col), (int, float))]
        if values:
            mean = sum(values) / len(values)
            summary_rows.append((col, mean))

    summary_html = "".join(
        f"<tr><td>{html.escape(name)}</td>"
        f"<td class='val'>{value:.3f}</td></tr>"
        for name, value in summary_rows
    )

    body_rows: list[str] = []
    for row in results:
        q = str(row.get("user_input", ""))[:80]
        cells = "".join(
            f"<td class='val'>{row[col]:.3f}</td>"
            if isinstance(row.get(col), (int, float))
            else f"<td>{html.escape(str(row.get(col, '')))[:40]}</td>"
            for col in metric_cols
        )
        body_rows.append(f"<tr><td>{html.escape(q)}</td>{cells}</tr>")
    metric_headers = "".join(f"<th>{html.escape(c)}</th>" for c in metric_cols)

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>AdaptiveRAG DeepEval Report — {html.escape(ran_at)}</title>
<style>
  body {{ font-family: system-ui, sans-serif; margin: 2rem; max-width: 1100px; }}
  h1 {{ margin-bottom: 0.2rem; }}
  .meta {{ color: #555; margin-bottom: 1.5rem; }}
  table {{ border-collapse: collapse; width: 100%; margin-bottom: 2rem; }}
  th, td {{ padding: 0.5rem 0.75rem; border-bottom: 1px solid #eaeaea; text-align: left; vertical-align: top; }}
  th {{ background: #fafafa; font-weight: 600; }}
  td.val {{ text-align: right; font-variant-numeric: tabular-nums; }}
  tr:hover {{ background: #fcfcff; }}
  .summary td.val {{ font-weight: 600; }}
</style>
</head>
<body>
<h1>AdaptiveRAG — DeepEval Report</h1>
<div class="meta">
  Ran at <strong>{html.escape(ran_at)}</strong>
  · Golden set: <code>{html.escape(str(golden_path))}</code>
  · Rows: <strong>{len(results)}</strong>
  · Judge LLM: <code>{html.escape(settings.LLM_MODEL)}</code>
</div>

<h2>Summary</h2>
<table class="summary">
  <thead><tr><th>Metric</th><th class="val">Mean</th></tr></thead>
  <tbody>{summary_html}</tbody>
</table>

<h2>Per-question scores</h2>
<table>
  <thead><tr><th>Query</th>{metric_headers}</tr></thead>
  <tbody>{''.join(body_rows)}</tbody>
</table>

<p style="color:#888;font-size:0.9em">
  Generated by <code>src/eval/run_deepeval.py</code>. Faithfulness scores claim-grounding,
  answer relevancy scores how well the answer addresses the question,
  contextual precision scores whether retrieved chunks are relevant. Higher is better
  on a 0&ndash;1 scale.
</p>
</body>
</html>
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="DeepEval eval over the golden set.")
    parser.add_argument("--golden", type=Path, default=DEFAULT_GOLDEN)
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Cap rows (handy for cost-bounded smoke runs).",
    )
    args = parser.parse_args()

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

    if not args.golden.exists():
        print(f"Golden set not found: {args.golden}", file=sys.stderr)
        return 2

    examples = load_golden(args.golden)
    eligible = [e for e in examples if e["expected_strategy"] in RETRIEVAL_STRATEGIES]
    if args.limit:
        eligible = eligible[: args.limit]

    print(
        f"Loaded {len(examples)} examples; {len(eligible)} are retrieval-bearing "
        f"(vector_only / hybrid)."
    )

    print("Collecting answers + contexts via the dispatcher:")
    rows = collect_runs(eligible)
    if not rows:
        print("No rows to evaluate. Did you ingest documents into Qdrant?", file=sys.stderr)
        return 1

    print(f"\nRunning DeepEval on {len(rows)} rows...")
    results = run_deepeval(rows)

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    ran_at = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    json_path = REPORTS_DIR / f"deepeval_{ran_at}.json"
    html_path = REPORTS_DIR / f"deepeval_{ran_at}.html"

    json_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    html_path.write_text(
        render_html(results, ran_at=ran_at, golden_path=args.golden), encoding="utf-8"
    )

    print()
    print("Per-metric means:")
    metric_cols = [
        c for c in results[0].keys()
        if c not in {"user_input", "response", "retrieved_contexts"}
    ] if results else []
    for col in metric_cols:
        values = [r.get(col) for r in results if isinstance(r.get(col), (int, float))]
        if values:
            print(f"  {col:<35} {sum(values)/len(values):.3f}")
    print()
    print(f"Reports written:")
    print(f"  {json_path}")
    print(f"  {html_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
