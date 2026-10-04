# Main Portfolio Sync Runbook

Portfolio sync and daily-news coverage intentionally use **Main only**.

## Source configuration

Keep real sheet IDs, gids, account data, and private exports outside this public repository.

```bash
export MINERVA_PORTFOLIO_HOLDINGS_SOURCE='https://docs.google.com/spreadsheets/d/<SHEET_ID>/export?format=csv&gid=<MAIN_HOLDINGS_GID>'
export MINERVA_PORTFOLIO_TRANSACTIONS_SOURCE='https://docs.google.com/spreadsheets/d/<SHEET_ID>/export?format=csv&gid=<MAIN_TRANSACTIONS_GID>'
```

Direct Google URLs require one numeric `gid` in the query. Minerva preserves `tq`, `range`, and `headers`, requests GViz, and uses exact `v` values rather than formatted `f` values. `--sheet-id` may be paired with either or both gid options; an omitted side retains local state. Generic CSV, JSON, JSONL, and YAML sources remain supported.

## Semantics

- When `Portfolio` exists, only trimmed, case-insensitive `Main` rows are imported; legacy sources without that column retain Main behavior. Closed Main securities remain in transaction history.
- The modern transaction contract is `Date, Type, Symbol, Shares, Price (USD), Total (USD), Portfolio`. Its dates, Buy/Sell action, positive finite numbers, and reported USD total are validated; cash is not recomputed. Legacy transactions remain permissive.
- Same-day source order is stable. Holdings weights use percentage points. Existing enrichment and Main-filtered watchlist state are preserved.
- All inputs and metadata are loaded, normalized, and rendered before current-state writes begin. Zero valid Main holdings fails closed.

## Verify and deploy

Run focused and full tests plus `git diff --check` and `python3 scripts/check_repo_privacy.py`. After merge, privately dry-run the configured gids and verify Main-only counts, exact values, reported cash, same-day order, closed-position history, watchlist isolation, and malformed-source behavior before enabling scheduled sync. Do not use live sources during repository tests.
