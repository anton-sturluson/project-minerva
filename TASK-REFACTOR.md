# Task: Style Refactor — Drop _v2, Fix Defensive Code, Crisp Type Annotations

You are refactoring the thesis card v2 implementation in this branch. This is a focused style/quality pass — NOT adding features.

## What To Do

### 1. Drop all `_v2` suffixes

The old `set_thesis_card` function was already removed. There is nothing to disambiguate. Rename everywhere:

| Old name | New name |
|---|---|
| `set_thesis_card_v2` | `set_thesis_card` |
| `_load_thesis_cards_v2` | `_load_thesis_cards` |
| `_write_thesis_cards_v2` | `_write_thesis_cards` |
| `_coerce_thesis_card_v2` | `_coerce_thesis_card` |
| event name `"thesis-set-v2"` | `"thesis-set"` |

Files to update:
- `src/harness/portfolio_state.py`
- `src/harness/commands/portfolio.py`
- `src/harness/morning_brief.py`
- `tests/test_harness/test_morning_brief.py`
- `tests/test_harness/test_thesis_cards.py`

### 2. Remove unnecessary defensive coercion on typed `str` parameters

The pattern `(value or "").strip()` is wrong when the parameter is typed as `str` (not `str | None`). If the type says `str`, trust it — use `value.strip()` directly.

**Rules:**
- Parameter typed `str` → use `value.strip()`. No `or ""` guard.
- Parameter typed `str | None` → `(value or "").strip()` is correct, keep it.
- Dict `.get()` results from JSON → `str(record.get("field") or "")` is correct, keep it.

**Only fix the new thesis card functions in `portfolio_state.py`:**
- `validate_fiscal_period(value: str)` — line ~409: change `(value or "").strip()` to `value.strip()`
- `set_thesis_card(...)` — `summary: str` param: change `(summary or "").strip()` to `summary.strip()`
- `add_thesis_metric(...)` — `name: str`, `value: str`, `period: str` params: change `(name or "").strip()` etc to `name.strip()` etc.
- `add_thesis_metric(...)` — `unit: str | None`, `date: str | None`, `source: str | None` params: keep `(unit or "").strip()` — these are correctly guarded.

Do NOT touch the older existing code in `portfolio_state.py` (adjacency functions, enrich, normalize, etc). Only fix the new thesis functions.

### 3. Make sure type annotations are crisp and complete

Review ALL new thesis functions and helpers in `portfolio_state.py` and `commands/portfolio.py`. Ensure:
- Every function has a return type annotation
- Every parameter has a type annotation
- No `Any` where a more specific type exists
- Use `str | None` not `Optional[str]`

### 4. Drop the duplicate key in morning_brief.py

In `prepare_evidence`, the prepared dict has both `"thesis_cards_by_ticker"` and `"thesis_ticker_index"` with the same data. Remove `"thesis_cards_by_ticker"` — keep only `"thesis_ticker_index"`.

## Rules

- Do NOT modify test assertions or test logic. Tests should pass without changes to test files (other than renaming `set_thesis_card_v2` → `set_thesis_card` in imports and calls).
- Run `.venv/bin/python -m pytest tests/ -x -q` after changes — all 274 tests must pass.
- Make ONE commit with message: `refactor(portfolio): drop _v2 naming, fix defensive coercion, crisp type annotations`

When completely finished, run: openclaw system event --text "Done: Thesis style refactor complete" --mode now
