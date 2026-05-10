"""Router-only evaluation.

Runs the adaptive router (no retrieval, no SQL execution, no synthesis)
against the golden set and reports per-strategy accuracy. Useful as a
fast CI gate — every router prompt change should bump or hold this
number, never silently regress it.

Usage:
    uv run python -m src.eval.run_routing_eval
    uv run python -m src.eval.run_routing_eval --golden src/eval/golden.jsonl
    uv run python -m src.eval.run_routing_eval --output src/eval/reports/routing.json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.routing import AdaptiveRouter
from src.routing.strategies import Strategy
from src.tools import SqlTool, SqlToolError

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("routing_eval")

DEFAULT_GOLDEN = Path("src/eval/golden.jsonl")
DEFAULT_REPORT = Path("src/eval/reports/routing.json")


def load_golden(path: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw or raw.startswith("//"):
                continue
            out.append(json.loads(raw))
    return out


def build_router() -> AdaptiveRouter:
    schema = ""
    sql_available = False
    try:
        tool = SqlTool()
        schema = tool.schema_summary()
        sql_available = True
    except SqlToolError:
        logger.warning(
            "SQL backend unavailable — router will be told no SQL exists. "
            "Expected sql_only/hybrid examples will be downgraded."
        )
    return AdaptiveRouter(sql_available=sql_available, schema_summary=schema)


def evaluate(
    router: AdaptiveRouter,
    examples: list[dict[str, Any]],
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    correct = 0
    by_expected: dict[str, list[bool]] = defaultdict(list)
    confusion: Counter[tuple[str, str]] = Counter()
    total_routing_ms = 0.0

    for ex in examples:
        query = ex["query"]
        expected = ex["expected_strategy"]
        try:
            decision, ms = router.classify(query)
            predicted = decision.strategy.value
            reasoning = decision.reasoning
        except Exception as exc:
            predicted = "ERROR"
            reasoning = str(exc)
            ms = 0.0

        is_correct = predicted == expected
        correct += int(is_correct)
        by_expected[expected].append(is_correct)
        confusion[(expected, predicted)] += 1
        total_routing_ms += ms

        rows.append(
            {
                "id": ex.get("id"),
                "query": query,
                "expected": expected,
                "predicted": predicted,
                "correct": is_correct,
                "reasoning": reasoning,
                "routing_ms": round(ms, 1),
            }
        )

    n = len(examples)
    overall = correct / n if n else 0.0
    by_strategy = {
        s: {
            "correct": sum(results),
            "total": len(results),
            "accuracy": round(sum(results) / len(results), 3) if results else None,
        }
        for s, results in sorted(by_expected.items())
    }

    return {
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "n_examples": n,
        "overall_accuracy": round(overall, 3),
        "avg_routing_ms": round(total_routing_ms / n, 1) if n else 0.0,
        "by_strategy": by_strategy,
        "confusion": [
            {"expected": e, "predicted": p, "count": c}
            for (e, p), c in sorted(confusion.items())
        ],
        "rows": rows,
    }


def print_summary(report: dict[str, Any]) -> None:
    print()
    print(f"Routing eval — {report['n_examples']} examples")
    print("=" * 60)
    print(f"  overall accuracy : {report['overall_accuracy']:.1%}")
    print(f"  avg latency      : {report['avg_routing_ms']:.0f} ms")
    print()
    print("  Per-strategy accuracy:")
    valid_strategies = {s.value for s in Strategy}
    for strategy, stats in report["by_strategy"].items():
        marker = "  " if strategy in valid_strategies else "??"
        acc = stats["accuracy"]
        bar = "#" * int((acc or 0) * 20)
        print(
            f"   {marker} {strategy:<14} {stats['correct']:>3}/{stats['total']:<3} "
            f"({acc:.1%}) {bar}"
        )
    print()
    print("  Misclassifications:")
    misses = [r for r in report["rows"] if not r["correct"]]
    if not misses:
        print("    none")
    else:
        for r in misses:
            print(
                f"    [{r['id']}] expected={r['expected']:<12} "
                f"predicted={r['predicted']:<12} :: {r['query'][:55]}"
            )
            print(f"        reason: {r['reasoning']}")
    print()


def main() -> int:
    parser = argparse.ArgumentParser(description="Router-only golden-set eval.")
    parser.add_argument("--golden", type=Path, default=DEFAULT_GOLDEN)
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT)
    parser.add_argument(
        "--threshold",
        type=float,
        default=None,
        metavar="P",
        help=(
            "If set (e.g. 0.85), exit with code 1 when overall accuracy < P. "
            "Default: no fail — print the report only (keeps tiny golden sets usable locally)."
        ),
    )
    args = parser.parse_args()

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

    if not args.golden.exists():
        print(f"Golden set not found: {args.golden}", file=sys.stderr)
        return 2

    examples = load_golden(args.golden)
    print(f"Loaded {len(examples)} examples from {args.golden}")

    router = build_router()
    print(f"Router model: {router.model} (sql_available={router.sql_available})")

    report = evaluate(router, examples)
    print_summary(report)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Report written to {args.output}")

    if args.threshold is not None and report["overall_accuracy"] < args.threshold:
        print(
            f"FAILED: accuracy {report['overall_accuracy']:.1%} "
            f"below threshold {args.threshold:.0%}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
