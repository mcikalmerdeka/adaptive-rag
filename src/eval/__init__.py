"""Evaluation framework.

- ``golden.jsonl`` — hand-curated Q&A pairs spanning all 5 strategies.
- ``run_routing_eval.py`` — router-only accuracy + per-strategy breakdown.
- ``run_deepeval.py`` — full pipeline through DeepEval (faithfulness, answer
  relevancy, contextual precision) + HTML report.
- ``reports/`` — generated outputs (gitignored).
"""
