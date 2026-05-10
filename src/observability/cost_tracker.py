"""Read-only Langfuse cost / usage reporter.

Langfuse already computes cost & token usage server-side from the model
+ token counts our ``CallbackHandler`` records. So we just hit the
public metrics endpoint instead of duplicating a price table here.

Used by:

- ``src/ui/admin_ui.py`` (the "Costs" tab in the Gradio app)
- ad-hoc CLI: ``uv run python -m src.observability.cost_tracker``

Returns plain Python dicts; no DataFrame / Pandas dependency, so this
module stays import-cheap.
"""

from __future__ import annotations

import argparse
import base64
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any

import httpx

from src.config import settings

logger = logging.getLogger(__name__)


@dataclass
class ModelUsage:
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    observation_count: int = 0


@dataclass
class DailyMetrics:
    day: str
    trace_count: int = 0
    observation_count: int = 0
    total_cost_usd: float = 0.0
    by_model: list[ModelUsage] = field(default_factory=list)


@dataclass
class CostSummary:
    """Aggregate over a date window."""

    from_day: str
    to_day: str
    total_traces: int
    total_observations: int
    total_cost_usd: float
    total_input_tokens: int
    total_output_tokens: int
    by_model: dict[str, ModelUsage]
    daily: list[DailyMetrics]
    enabled: bool = True
    error: str | None = None

    @property
    def total_tokens(self) -> int:
        return self.total_input_tokens + self.total_output_tokens


def _disabled_summary(reason: str) -> CostSummary:
    today = date.today().isoformat()
    return CostSummary(
        from_day=today,
        to_day=today,
        total_traces=0,
        total_observations=0,
        total_cost_usd=0.0,
        total_input_tokens=0,
        total_output_tokens=0,
        by_model={},
        daily=[],
        enabled=False,
        error=reason,
    )


def fetch_cost_summary(
    *,
    days: int = 7,
    user_id: str | None = None,
    tags: list[str] | None = None,
    timeout: float = 15.0,
) -> CostSummary:
    """Pull a cost / usage rollup from Langfuse for the last ``days`` days.

    Returns a :class:`CostSummary` even when Langfuse is disabled (with
    ``enabled=False`` set), so the UI can render a friendly empty state.
    """
    if not settings.langfuse_enabled:
        return _disabled_summary("Langfuse keys not configured.")

    today = datetime.now(timezone.utc).date()
    from_day = today - timedelta(days=days - 1)
    base = settings.LANGFUSE_HOST.rstrip("/")
    url = f"{base}/api/public/metrics/daily"

    params: dict[str, Any] = {
        "fromTimestamp": f"{from_day.isoformat()}T00:00:00.000Z",
        "toTimestamp": f"{today.isoformat()}T23:59:59.999Z",
        "limit": 100,
    }
    if user_id:
        params["userId"] = user_id
    if tags:
        for t in tags:
            params.setdefault("tags", []).append(t)

    auth_pair = f"{settings.LANGFUSE_PUBLIC_KEY}:{settings.LANGFUSE_SECRET_KEY}"
    auth_header = "Basic " + base64.b64encode(auth_pair.encode()).decode()

    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.get(
                url,
                params=params,
                headers={"Authorization": auth_header},
            )
            resp.raise_for_status()
            payload = resp.json()
    except httpx.HTTPStatusError as exc:
        msg = f"Langfuse API returned {exc.response.status_code}: {exc.response.text[:200]}"
        logger.warning(msg)
        return _disabled_summary(msg)
    except Exception as exc:  # noqa: BLE001
        msg = f"Langfuse API call failed: {exc}"
        logger.warning(msg)
        return _disabled_summary(msg)

    return _parse_payload(payload, from_day=from_day.isoformat(), to_day=today.isoformat())


def _parse_payload(
    payload: dict[str, Any],
    *,
    from_day: str,
    to_day: str,
) -> CostSummary:
    """Convert the Langfuse daily-metrics payload into a CostSummary."""
    daily_rows: list[DailyMetrics] = []
    by_model: dict[str, ModelUsage] = {}
    total_traces = 0
    total_obs = 0
    total_cost = 0.0
    total_in = 0
    total_out = 0

    for entry in payload.get("data", []):
        day = entry.get("date") or ""
        n_traces = int(entry.get("countTraces") or 0)
        n_obs = int(entry.get("countObservations") or 0)
        cost = float(entry.get("totalCost") or 0.0)

        usage_rows: list[ModelUsage] = []
        for u in entry.get("usage", []) or []:
            model = u.get("model") or "unknown"
            input_tok = int(u.get("inputUsage") or 0)
            output_tok = int(u.get("outputUsage") or 0)
            total_tok = int(u.get("totalUsage") or (input_tok + output_tok))
            mu = ModelUsage(
                model=model,
                input_tokens=input_tok,
                output_tokens=output_tok,
                total_tokens=total_tok,
                cost_usd=float(u.get("totalCost") or 0.0),
                observation_count=int(u.get("countObservations") or 0),
            )
            usage_rows.append(mu)

            agg = by_model.setdefault(model, ModelUsage(model=model))
            agg.input_tokens += mu.input_tokens
            agg.output_tokens += mu.output_tokens
            agg.total_tokens += mu.total_tokens
            agg.cost_usd += mu.cost_usd
            agg.observation_count += mu.observation_count

            total_in += mu.input_tokens
            total_out += mu.output_tokens

        daily_rows.append(
            DailyMetrics(
                day=day,
                trace_count=n_traces,
                observation_count=n_obs,
                total_cost_usd=cost,
                by_model=usage_rows,
            )
        )
        total_traces += n_traces
        total_obs += n_obs
        total_cost += cost

    daily_rows.sort(key=lambda r: r.day, reverse=True)
    return CostSummary(
        from_day=from_day,
        to_day=to_day,
        total_traces=total_traces,
        total_observations=total_obs,
        total_cost_usd=total_cost,
        total_input_tokens=total_in,
        total_output_tokens=total_out,
        by_model=by_model,
        daily=daily_rows,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Pull cost summary from Langfuse.")
    parser.add_argument("--days", type=int, default=7)
    args = parser.parse_args()

    summary = fetch_cost_summary(days=args.days)
    if not summary.enabled:
        print(f"Cost tracking unavailable: {summary.error}")
        return 1

    print(f"Cost summary {summary.from_day} -> {summary.to_day}")
    print("=" * 60)
    print(f"  Traces       : {summary.total_traces}")
    print(f"  Observations : {summary.total_observations}")
    print(f"  Tokens       : {summary.total_tokens:,} "
          f"(in={summary.total_input_tokens:,}, out={summary.total_output_tokens:,})")
    print(f"  Cost         : ${summary.total_cost_usd:.4f}")
    print()
    if summary.by_model:
        print("  By model:")
        for model, usage in sorted(
            summary.by_model.items(), key=lambda kv: kv[1].cost_usd, reverse=True
        ):
            print(
                f"    {model:<35} cost=${usage.cost_usd:7.4f} "
                f"in={usage.input_tokens:>8,} out={usage.output_tokens:>8,}"
            )
    print()
    if summary.daily:
        print("  By day:")
        for d in summary.daily:
            print(
                f"    {d.day} traces={d.trace_count:>4} "
                f"obs={d.observation_count:>4} cost=${d.total_cost_usd:.4f}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
