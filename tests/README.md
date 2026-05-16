# AdaptiveRAG Test Suite

All **147 tests pass**.

## What Got Built

### Configuration

- `pyproject.toml` — pytest configuration with markers for `slow` and `integration` tests

### 8 Test Files (147 tests total)


| File                            | Tests | Coverage                                                                                                                                                                                                                 |
| ------------------------------- | ----- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `tests/test_settings.py`        | 13    | Env helper functions, Settings defaults, frozen dataclass immutability, `langfuse_enabled` property                                                                                                                      |
| `tests/test_strategies.py`      | 12    | Strategy enum values, labels map, `SQL_STRATEGIES` frozenset membership                                                                                                                                                  |
| `tests/test_prompts.py`         | 7     | System prompt mentions all strategies, schema template placeholder, few-shot example completeness                                                                                                                        |
| `tests/test_metadata.py`        | 13    | `compute_doc_id` SHA256 determinism, `chunk_uuid` UUID5 namespace isolation, `build_chunk_metadata` schema fields                                                                                                        |
| `tests/test_file_detector.py`   | 22    | Extension→format mapping, case insensitivity, `validate()` error cases, supported extensions list                                                                                                                        |
| `tests/test_sql_tool.py`        | 47    | **Security-critical:** `_clean` markdown fence stripping, `_validate` allowlist (SELECT/WITH only), forbidden keyword regex against 12+ DDL/write keywords, multi-statement detection, `_inject_limit` append/skip logic |
| `tests/test_ocr_cache.py`       | 9     | SHA256 key determinism, get/put round-trip, overwrite behavior, directory auto-creation                                                                                                                                  |
| `tests/test_embedding_cache.py` | 24    | Namespace-isolated keys, float32 round-trip, `embed_query` hit/miss, `embed_documents` batch hit/miss mixing, factory function                                                                                           |


### Key Design Choices

- **No external test dependencies** — uses only `pytest` (already installed) and `unittest.mock` (stdlib)
- **No API keys or DB required** — everything mocks or tests pure logic
- **Fast** — 147 tests in ~11 seconds
- **Honest about limitations** — the SQL regex tests document that the simple regex matches forbidden keywords anywhere in the string (not just as SQL tokens), which is intentional defense-in-depth

## How to Run

```bash
# All tests
uv run pytest -v

# Unit tests only (same result currently — no slow/integration tests yet)
uv run pytest -v -m "not slow and not integration"
```

## Architecture

The test suite now covers the pure logic and security-critical components that were previously untested. The integration evals (`run_routing_eval`, `run_deepeval`) remain as the higher-level validation layer.

## Test Organization

```
tests/
├── __init__.py
├── test_embedding_cache.py    # Disk cache for embeddings (SHA256, namespace, hit/miss)
├── test_file_detector.py      # Extension/MIME detection and validation
├── test_metadata.py           # Chunk metadata determinism and schema
├── test_ocr_cache.py          # OCR result disk cache (SHA256 keying)
├── test_prompts.py            # Router prompt completeness and few-shot coverage
├── test_settings.py           # Env var parsing and frozen Settings dataclass
├── test_sql_tool.py           # SQL safety guards, regex patterns, LIMIT injection
└── test_strategies.py         # Strategy enum, labels, capability sets
```

