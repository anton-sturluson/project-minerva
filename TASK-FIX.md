# Task: Fix PR Review Comments + Production Crash

Three things to fix, then push. One commit.

## Bug: Production Crash

When running against the main checkout's `hard-disk/data/01-portfolio/current/thesis-cards.json`, `minerva portfolio thesis list` crashes because:
1. Old-schema cards have 9+ items in `key_expectations` and 10+ in `disconfirming_signals`
2. The `_coerce_thesis_card` function passes these through `_normalize_thesis_list` which enforces the 5-item cap
3. The cap rejects the coercion and throws a ValueError

**Fix: Remove ALL legacy coercion machinery entirely.** Per Anton's review: "We're going to discard old cards, so we shouldn't have any unnecessary check on legacy." Delete:
- `_contains_legacy_thesis_cards()`
- `_coerce_thesis_card()`
- `_backup_thesis_cards()`
- The `backup_old_schema` parameter from `_load_thesis_cards`
- The legacy coercion path in `render_thesis_markdown()`
- Any related imports or references

`_load_thesis_cards` should simply load the JSON, filter to only cards that have a `card_id` key (silently skip legacy cards), and return them. `render_thesis_markdown` should do the same — only render cards with `card_id`, skip anything else.

## Fix 1: Make `settings` required across command functions

The `settings or get_settings()` pattern exists in every command function. Fix it:

1. Change ALL command functions in `src/harness/commands/portfolio.py` from `settings: HarnessSettings | None = None` to `settings: HarnessSettings`
2. Have the Typer CLI wrapper functions (the `@app.command` / `@thesis_app.command` decorated functions) call `get_settings()` and pass it explicitly
3. The `dispatch()` function and `_dispatch_*` functions should also take `settings: HarnessSettings` (not optional). The CLI entrypoint in `cli.py` passes settings from `get_settings()`.
4. Do the same for ALL command files that have this pattern: `portfolio.py`, `evidence.py`, `extract.py`, `sec.py`, `analyze.py`, `fileinfo.py`, `brief.py`, `valuation.py`, `plot.py`, `research.py`

Check how `dispatch_command` in `cli.py` calls into each command's dispatch — make sure it passes `get_settings()`.

## Fix 2: Trust typed data — drop unnecessary str() wrapping

In `portfolio_state.py`, fix the thesis functions:

- `get_thesis_by_ticker`: change `str(item.get("card_id", ""))` to `item["card_id"]` in the sort key. Change `str(symbol).strip().upper()` to `symbol.strip().upper()` in the ticker matching.
- Any other place in the NEW thesis code where `str()` wraps a value that's already typed as `str` in the TypedDict.

Do NOT touch older existing code (adjacency, enrich, normalize functions) — only the new thesis functions.

## Rules

- Run `.venv/bin/python -m pytest tests/ -x -q` after changes — all tests must pass
- Also test: `cd /Users/charlie-buffet/Documents/project-minerva && minerva portfolio thesis list` (this must NOT crash even with old-schema cards in thesis-cards.json — it should skip them)
- ONE commit: `fix(portfolio): require settings, drop legacy coercion, trust typed data`
- Push to origin after commit: `git push origin fix/portfolio-thesis-cli-schema`

When completely finished, run: openclaw system event --text "Done: Thesis fix complete" --mode now
