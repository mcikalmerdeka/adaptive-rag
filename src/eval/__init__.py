"""Evaluation framework.

- ``golden.jsonl`` — hand-curated Q&A pairs spanning all 5 strategies.
- ``run_routing_eval.py`` — router-only accuracy + per-strategy breakdown.
- ``run_ragas.py`` — full pipeline through Ragas (faithfulness, answer
  relevancy, context precision, context recall) + HTML report.
- ``reports/`` — generated outputs (gitignored).
"""
