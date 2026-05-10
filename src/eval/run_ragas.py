"""End-to-end Ragas evaluation.

For every golden example whose expected strategy involves retrieval
(``vector_only`` or ``hybrid``), runs the dispatcher to produce an
answer + chunks, then scores it with Ragas:

- ``Faithfulness``                        — answer claims are grounded in context
- ``ResponseRelevancy``                   — answer addresses the question
- ``LLMContextPrecisionWithoutReference`` — retrieved chunks are relevant

Why no ``LLMContextRecall``: it needs a hand-written "ground truth"
answer. Our golden file only has ``answer_must_contain`` keywords as
weak proxies. Adding gold answers per question is doable, but defer it
until the synthesis prompt is stable enough to make scores trustworthy.

Output:

- ``src/eval/reports/ragas_<timestamp>.json`` — raw scores per question
- ``src/eval/reports/ragas_<timestamp>.html`` — quick visual summary

Usage:
    uv run python -m src.eval.run_ragas
    uv run python -m src.eval.run_ragas --limit 1   # cheapest: one retrieval row only

The bundled ``golden.jsonl`` is intentionally tiny (smoke set). Each
``vector_only`` / ``hybrid`` row drives a full dispatch + three Ragas
metrics (several LLM calls per row).

**Python 3.14 + nest_asyncio:** Ragas wraps metric work in ``asyncio.wait_for``,
which crashes when ``nest_asyncio`` leaves ``current_task()`` as ``None``.
Ragas then records ``nan`` for every metric (JSON shows ``null``). This
module patches ``asyncio.wait_for`` for the duration of ``evaluate()``.
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
logger = logging.getLogger("ragas_eval")

DEFAULT_GOLDEN = Path("src/eval/golden.jsonl")
REPORTS_DIR = Path("src/eval/reports")

# Ragas installs nest_asyncio, which breaks ``asyncio.current_task()`` inside
# nested coroutines under ``asyncio.run()`` (Python 3.14+ reproduces easily).
# The stdlib ``wait_for()`` implementation always enters ``asyncio.timeout()``,
# whose context manager refuses to run when ``current_task()`` is ``None``.
# Ragas catches that failure and substitutes ``nan`` → JSON reports show
# ``null`` scores. Monkey-patch ``wait_for`` only while ``evaluate()`` runs.
_WAIT_FOR_ORIG: Any = None


def _patch_wait_for_if_needed() -> None:
    """Install a nest_asyncio-compatible ``asyncio.wait_for`` (idempotent)."""
    import asyncio

    global _WAIT_FOR_ORIG
    if _WAIT_FOR_ORIG is not None:
        return

    _WAIT_FOR_ORIG = asyncio.wait_for

    async def _wait_for_nest_compat(fut: Any, timeout: float | None = None) -> Any:
        # Under nest_asyncio, ``timeouts.timeout()`` cannot attach to the
        # current task (there isn't one Ragas bookkeeping sees).
        # LLM timeouts are still enforced by ``ChatOpenAI.request_timeout``.
        if asyncio.current_task() is None:
            return await fut

        try:
            return await _WAIT_FOR_ORIG(fut, timeout)
        except RuntimeError as exc:
            if "Timeout should be used inside a task" in str(exc):
                logger.warning(
                    "Ragas wait_for workaround: falling back to unbounded await "
                    "(nest_asyncio + asyncio.timeout incompatibility)."
                )
                return await fut
            raise

    asyncio.wait_for = _wait_for_nest_compat  # type: ignore[assignment]


def _restore_wait_for() -> None:
    import asyncio

    global _WAIT_FOR_ORIG
    if _WAIT_FOR_ORIG is None:
        return
    asyncio.wait_for = _WAIT_FOR_ORIG  # type: ignore[assignment]
    _WAIT_FOR_ORIG = None


# Only these strategies have retrieved chunks worth grading.
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


def run_ragas(rows: list[dict[str, Any]]) -> Any:
    """Build a Ragas dataset and score it. Returns the DataFrame."""
    if not rows:
        raise RuntimeError("No rows to evaluate.")

    # Imports kept inside the function so loading the module is cheap and
    # the (heavy) Ragas import stack only fires when actually needed.
    from langchain_openai import ChatOpenAI, OpenAIEmbeddings
    from ragas import EvaluationDataset, SingleTurnSample, evaluate
    from ragas.embeddings import LangchainEmbeddingsWrapper
    from ragas.llms import LangchainLLMWrapper
    from ragas.metrics import (
        Faithfulness,
        LLMContextPrecisionWithoutReference,
        ResponseRelevancy,
    )

    samples = [
        SingleTurnSample(
            user_input=row["query"],
            response=row["answer"],
            retrieved_contexts=row["contexts"],
        )
        for row in rows
    ]
    dataset = EvaluationDataset(samples=samples)

    # Use the cheaper synthesis model as the evaluator too — frontier
    # judges aren't required for an internal scorecard, and keeping the
    # model identical to production removes one source of variance.
    judge_llm = LangchainLLMWrapper(
        ChatOpenAI(model=settings.LLM_MODEL, temperature=0.0)
    )
    judge_embeddings = LangchainEmbeddingsWrapper(
        OpenAIEmbeddings(model=settings.DENSE_MODEL)
    )

    _patch_wait_for_if_needed()
    try:
        result = evaluate(
            dataset,
            metrics=[
                Faithfulness(llm=judge_llm),
                ResponseRelevancy(llm=judge_llm, embeddings=judge_embeddings),
                LLMContextPrecisionWithoutReference(llm=judge_llm),
            ],
            llm=judge_llm,
            embeddings=judge_embeddings,
            show_progress=True,
        )
    finally:
        _restore_wait_for()

    return result.to_pandas()


def render_html(df: Any, *, ran_at: str, golden_path: Path) -> str:
    """Compact self-contained HTML report."""
    metric_cols = [
        c
        for c in df.columns
        if c not in {"user_input", "response", "retrieved_contexts", "reference"}
    ]
    summary_rows = []
    for col in metric_cols:
        try:
            mean = float(df[col].mean())
            summary_rows.append((col, mean))
        except Exception:  # noqa: BLE001
            continue

    summary_html = "".join(
        f"<tr><td>{html.escape(name)}</td>"
        f"<td class='val'>{value:.3f}</td></tr>"
        for name, value in summary_rows
    )

    # Per-row table — show short query + scores.
    body_rows: list[str] = []
    for _, row in df.iterrows():
        q = str(row.get("user_input", ""))[:80]
        cells = "".join(
            f"<td class='val'>{row[col]:.3f}</td>"
            if isinstance(row[col], (int, float))
            else f"<td>{html.escape(str(row[col]))[:40]}</td>"
            for col in metric_cols
        )
        body_rows.append(f"<tr><td>{html.escape(q)}</td>{cells}</tr>")
    metric_headers = "".join(f"<th>{html.escape(c)}</th>" for c in metric_cols)

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>AdaptiveRAG Ragas Report — {html.escape(ran_at)}</title>
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
<h1>AdaptiveRAG — Ragas Report</h1>
<div class="meta">
  Ran at <strong>{html.escape(ran_at)}</strong>
  · Golden set: <code>{html.escape(str(golden_path))}</code>
  · Rows: <strong>{len(df)}</strong>
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
  Generated by <code>src/eval/run_ragas.py</code>. Faithfulness scores claim-grounding,
  response relevancy scores how well the answer addresses the question,
  context precision scores whether retrieved chunks are relevant. Higher is better
  on a 0&ndash;1 scale.
</p>
</body>
</html>
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Ragas eval over the golden set.")
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

    print(f"\nRunning Ragas on {len(rows)} rows...")
    df = run_ragas(rows)

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    ran_at = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    json_path = REPORTS_DIR / f"ragas_{ran_at}.json"
    html_path = REPORTS_DIR / f"ragas_{ran_at}.html"

    df.to_json(json_path, orient="records", indent=2)
    html_path.write_text(
        render_html(df, ran_at=ran_at, golden_path=args.golden), encoding="utf-8"
    )

    print()
    print("Per-metric means:")
    metric_cols = [
        c
        for c in df.columns
        if c not in {"user_input", "response", "retrieved_contexts", "reference"}
    ]
    for col in metric_cols:
        try:
            print(f"  {col:<35} {df[col].mean():.3f}")
        except Exception:  # noqa: BLE001
            continue
    print()
    print(f"Reports written:")
    print(f"  {json_path}")
    print(f"  {html_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
