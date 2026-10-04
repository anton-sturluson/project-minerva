# Main Portfolio Sync Runbook

Minerva portfolio sync and daily-news coverage intentionally use **Main only**. This is not a multi-portfolio importer or monitor.

## Source configuration

Configure automation with environment-specific placeholders; never put real sheet IDs, gids, account data, or private exports in this public repository.

```bash
export MINERVA_PORTFOLIO_HOLDINGS_SOURCE='https://docs.google.com/spreadsheets/d/<SHEET_ID>/export?format=csv&gid=<MAIN_HOLDINGS_GID>'
export MINERVA_PORTFOLIO_TRANSACTIONS_SOURCE='https://docs.google.com/spreadsheets/d/<SHEET_ID>/export?format=csv&gid=<MAIN_TRANSACTIONS_GID>'
export MINERVA_PORTFOLIO_WATCHLIST_SOURCE='<PRIVATE_LOCAL_OR_REMOTE_SOURCE>'
```

Alternatively, pass `--sheet-id`, `--holdings-gid`, and `--transactions-gid`. Both gids are required when that mode is used. A direct Google Sheets URL must select a tab by numeric `gid`, or by the exact `sheet=Main Portfolio` name. `Current Portfolio`, another named tab, and first-tab fallback are rejected. Stable gids are preferred because tab renames do not change them.

Google CSV export URLs remain accepted, but Minerva upgrades them internally to a Google Visualization query and reads each cell's unformatted `v` value rather than its rounded display `f` value. Supported query semantics such as `gid`, `sheet`, `range`, `tq`, and `headers` are preserved. Generic local/remote CSV, JSON, JSONL, and YAML remain supported.

## Main filtering and normalized values

- A source with a `Portfolio` column contributes only rows labeled `Main` (case-insensitive after trimming). Blank, invalid, and other explicit labels are excluded rather than defaulted.
- A legacy source with no `Portfolio` column defaults to Main for backward compatibility.
- Filtering uses the transaction row's portfolio label, not current ticker membership, so valid history for a closed Main position remains available.
- The modern transaction shape is `Date, Type, Symbol, Shares, Price (USD), Total (USD), Portfolio`. Buy/sell, date, positive finite shares, and positive finite price are required. USD-priced records require their positive reported USD cash total; a missing column, empty total or conflicting currency fails validation. Cash is preserved, never recomputed from display-rounded inputs. Legacy records without USD-specific columns may omit reported cash.
- Dates normalize from ISO, `mm/dd/YYYY`, or `mm/dd/YY`. Results sort newest first and retain source order within one day.
- Currency/accounting strings and percentages are parsed. Holdings weights are stored in **percentage points**: GViz `0.55` and CSV `55%` both become `55`. Existing generic JSON numeric values are retained as supplied for compatibility.
- Blank spreadsheet rows and non-security cash/total rows are skipped. Zero valid Main holdings fails closed.

Holdings and transactions are fetched and validated before current state is replaced. Recoverable snapshots restore current outputs and history if a write raises an exception; if restoration itself fails, remaining recovery files are retained and their location is reported. This assumes a single writer: it is not concurrent-reader isolation or a crash-atomic database transaction. Watchlist, enrichment, adjacency, and thesis metadata continue to carry forward through a successful sync.

## Regression checks

Use the repository's existing environment; do not use live sources for regression tests:

```bash
PYTHONPATH="$PWD/src" <PARENT_REPO>/.venv/bin/python -m pytest -q \
  tests/test_harness/test_portfolio_main_sync.py \
  tests/test_harness/test_csv_normalization.py
python3 scripts/check_repo_privacy.py
```

Before deployment after merge, an operator should run a private dry run against the configured stable gids and verify:

1. holdings and transaction counts contain Main only;
2. fractional shares, prices, and reported totals match unformatted sheet values;
3. same-day transaction order and historical closed positions are retained;
4. daily-news universe contains no other portfolio groups;
5. malformed-source simulation leaves the prior current state unchanged.

Do not perform production workbook, scheduler, application-database, or live state writes as part of repository testing.

## External editing instructions

The shared portfolio-editing skill is operational configuration outside this public repository. After this change is merged, its operator should update it separately to:

- write the seven-column transaction schema above;
- label intended rows exactly `Main` and never use blank as an alias;
- retain exact fractional shares, USD price, and reported USD cash total;
- use stable Main tab gids in automation; and
- treat Minerva as Main-only rather than asking it to ingest or monitor additional groups.

Keep user-specific workbook details, examples, identities, and quantities in the private skill/configuration. Do not copy them into repository docs or fixtures.
