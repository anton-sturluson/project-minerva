# Task: Thesis Card v2 — TDD Implementation

You are implementing a thesis card schema and CLI overhaul for the Minerva investment harness. This is a TDD implementation using RED-GREEN-REFACTOR with a commit at each step.

## Context

The project is a Python CLI tool (`minerva`) built with Typer. The codebase has a clean two-layer split:
1. **State layer** (`src/harness/portfolio_state.py`) — pure functions that read/write JSON, render markdown. No CLI, no Typer.
2. **Command layer** (`src/harness/commands/portfolio.py`) — Typer wrappers + `_dispatch_*` functions for `minerva run` pipe routing.

Tests live in `tests/test_harness/test_morning_brief.py`. Run with: `.venv/bin/python -m pytest tests/test_harness/test_morning_brief.py -x -q`

The project uses `uv` for dependency management. The virtualenv is at `.venv/`. Use `.venv/bin/python` to run tests.

## What We Are Changing

### 1. New Thesis Card Schema

Old schema (being replaced):
```json
{
  "security_id": "GTLB",
  "thesis_summary": "...",
  "key_expectations": ["..."],
  "disconfirming_signals": ["..."],
  "updated_at": "..."
}
```

New schema:
```json
{
  "card_id": "string (primary key, lowercase kebab-style)",
  "ticker_symbols": ["GTLB"],
  "summary": "string (compact pitch)",
  "core_thesis": ["string (max 5)"],
  "key_metrics": [
    {
      "name": "NRR",
      "unit": "%",
      "observations": [
        {"period": "Q1 FY2027", "date": "2026-06-02", "value": "116%", "source": "earnings call"}
      ]
    }
  ],
  "signals": ["string (max 5)"],
  "updated_at": "ISO timestamp"
}
```

**Constraints:**
- `card_id`: required, lowercase kebab-style
- `ticker_symbols`: required, at least one, uppercased/syntax-validated (no universe membership check)
- `core_thesis`: max 5 items
- `key_metrics`: max 5 metric definitions per card, unlimited observations per metric
- `signals`: max 5 items
- Metric observation `period` format is strictly fiscal: `FY2026`, `H1 FY2026`, `H2 FY2026`, `Q1 FY2026`, `Q2 FY2026`, `Q3 FY2026`, `Q4 FY2026` — reject anything else with inline format examples
- Metric observation required fields: `value` + `period`. `date` and `source` are optional.
- `value` is stored as string (supports %, $, ratios, "not disclosed", ranges)
- `source` is free text

### 2. CLI Commands

```text
minerva portfolio thesis list              # List all thesis cards
minerva portfolio thesis show <CARD_ID>    # Show one card with metric tables
minerva portfolio thesis by-ticker <TICKER> # Show all cards linked to a ticker
minerva portfolio thesis set <CARD_ID>     # Create/replace card definition
    --ticker GTLB --ticker MU              # Required, repeatable
    --summary "..."                        # Required
    --core-thesis "..."                    # Repeatable, max 5
    --signal "..."                         # Repeatable, max 5
minerva portfolio thesis metric add <CARD_ID>  # Append metric observation
    --name NRR                             # Required
    --period "Q1 FY2027"                   # Required, fiscal format validated
    --value "116%"                         # Required
    [--date 2026-06-02]                    # Optional
    [--source "earnings call"]             # Optional
    [--unit "%"]                           # Optional
minerva portfolio thesis render            # Render thesis-cards.md to disk
```

### 3. Key Behaviors

- `set` REPLACES `summary`, `ticker_symbols`, `core_thesis`, `signals` — but PRESERVES existing `key_metrics`
- `set` always replaces; it is not a merge/patch for definition fields
- First write to `thesis-cards.json` when old-schema cards exist: back up to `hard-disk/data/01-portfolio/backups/thesis-cards-YYYYMMDD-HHMMSS.json`
- Semicolons also accepted as delimiters for list fields (convenience fallback)
- `show` and `by-ticker` should render metric observations as markdown tables
- `by-ticker` returns all cards whose `ticker_symbols` includes the queried ticker
- All error messages follow the create-cli waypoint pattern: what went wrong, what to do instead, examples

### 4. Morning Brief Integration

`prepare_evidence` in `morning_brief.py` loads thesis_cards into `prepared-evidence.json`. Update the key from `security_id` to `card_id`, and add a secondary ticker index so briefs can cross-reference events to theses.

## Implementation Plan — TDD RED-GREEN-REFACTOR

### Phase 1: RED — Write Failing Tests First

Add a new test file `tests/test_harness/test_thesis_cards.py`.

Write these 4 integration tests that all FAIL because the new functions dont exist yet:

**Test 1: `test_thesis_card_lifecycle`**
Full CRUD against a real temp workspace:
- `set` a card with card_id, tickers, summary, core_thesis, signals
- Verify JSON on disk has correct new schema
- `set` again with different summary/signals -> verify replaced, key_metrics preserved (empty)
- Add 2 metric observations via `add_thesis_metric`
- Verify observations persisted in JSON
- `set` the card again -> verify metrics survived the replacement
- Verify `thesis-cards.md` renders with metric tables

**Test 2: `test_thesis_by_ticker_cross_card`**
- Create 3 cards: `gtlb` (tickers: [GTLB]), `memory-hbm` (tickers: [MU, SK-HYNIX]), `mu-specific` (tickers: [MU])
- `get_thesis_by_ticker("MU")` -> returns 2 cards
- `get_thesis_by_ticker("GTLB")` -> returns 1 card
- `get_thesis_by_ticker("AAPL")` -> returns empty list

**Test 3: `test_thesis_metric_validation_and_caps`**
- Add metric with valid period `Q1 FY2027` -> succeeds
- Add metric with invalid period `2026 Q1` -> raises ValueError with format examples in the message
- Add 5 different metric names -> add a 6th -> raises ValueError with cap message
- Add multiple observations to same metric -> verify both present in output

**Test 4: `test_thesis_set_preserves_metrics_and_backs_up_old_schema`**
- Manually write an old-schema card to thesis-cards.json (with `security_id`, `key_expectations`, `disconfirming_signals`)
- Call new `set` -> verify backup file created in `backups/` directory
- Verify new card written with new schema fields
- Verify the backup contains the original old-schema data

Commit: `test(portfolio): add failing thesis card v2 integration tests`

### Phase 2: GREEN — Implement Until Tests Pass

Implement in this order:

1. **State layer** (`src/harness/portfolio_state.py`):
   - `validate_fiscal_period(value: str) -> str` — regex `^(FY\d{4}|[HQ][1-4] FY\d{4})$`
   - `set_thesis_card_v2(workspace_root, *, card_id, ticker_symbols, summary, core_thesis, signals)` — upsert card preserving metrics, backup old schema
   - `add_thesis_metric(workspace_root, *, card_id, name, unit, period, value, date, source)` — append observation, enforce caps
   - `get_thesis_by_ticker(workspace_root, *, ticker) -> list[dict]`
   - Updated `render_thesis_markdown()` for new schema with metric tables

2. **Command layer** (`commands/portfolio.py`):
   - New Typer subcommands on `thesis_app`: `list`, `show`, `set`, `by-ticker`, `metric add`, `render`
   - Updated `_dispatch_thesis` for `minerva run` routing
   - Error messages use `error_result` / `abort_with_help` from `commands/common.py`

3. **Morning brief** (`morning_brief.py`):
   - Update `prepare_evidence` to key thesis_cards by `card_id` and add ticker secondary index

Commit: `feat(portfolio): implement thesis card v2 schema and CLI commands`

### Phase 3: REFACTOR — Clean Up

- Remove old `set_thesis_card` function
- Update old test references (the existing `test_portfolio_sync_and_curation_render_state` calls `set_thesis_card` — update to v2)
- Clean up imports
- Make sure ALL existing tests still pass: `.venv/bin/python -m pytest tests/ -x -q`

Commit: `refactor(portfolio): remove old thesis card schema, update all references`

### Phase 4: Draft PR

```bash
git push -u origin fix/portfolio-thesis-cli-schema
gh pr create --title "feat(portfolio): thesis card v2 schema and CLI" --body "..." --draft
```

## IMPORTANT RULES

- Run tests with `.venv/bin/python -m pytest` (NOT `pytest` directly)
- Commit after EACH TDD phase (RED, GREEN, REFACTOR) with descriptive messages
- Do NOT create heavily mocked tests — all tests should work against real temp directories
- Make sure ALL existing tests pass before the final commit
- Follow existing code patterns — look at how `set_thesis_card`, `add_adjacency_entry`, `render_adjacency_markdown` work
- Use `error_result` from `commands/common.py` for error formatting
- Use existing helpers: `write_json`, `load_json`, `append_jsonl`, `now_utc_iso`, `canonical_security_id`, `update_history_render`

When completely finished, run: openclaw system event --text "Done: Thesis card v2 implementation complete" --mode now
