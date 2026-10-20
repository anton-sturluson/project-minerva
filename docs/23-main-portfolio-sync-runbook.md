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

## Scheduled two-stage flow

The scheduler runs one fixed shell launcher, using the already-configured source environment:

```bash
./scripts/run_morning_brief_scheduled.sh --handoff-job "$CHILD_JOB_UUID"
```

After the existing clean-main checks and fast-forward, it runs the existing `minerva portfolio sync` command, then `openclaw automations run "$CHILD_JOB_UUID" --json`. A failed command stops the launcher: failed sync cannot start the agent. The sync date uses New York time. Missing source settings fail rather than falling back to cached inputs.

There is no Python helper, receipt, hash, expiry rule, or extra state file. The CLI owns sync and job-admission error handling. Successful startup is silent; failures show the command output. Only the launcher is scheduled; the existing agent job stays disabled for automatic scheduling and is started explicitly after sync. Admission is not completion; the agent delivers the brief.

### Required child prompt instruction

> Portfolio sync has already succeeded before you started. Use the synced Main portfolio files, not memory or another spreadsheet fetch. Do not run portfolio sync or reconstruct source URLs. Determine `TODAY` in `America/New_York` and run `./scripts/run_morning_brief.sh "$TODAY"` from the main checkout. Follow the existing synthesis instructions.

`run_morning_brief.sh` is collection-only: it reads the synced portfolio and starts with filings. It has no portfolio-sync command, source-URL handling, or sync-mode flags. It trusts the successful preceding command, so do not start this agent independently or overlap runs. Keep the same workspace and current portfolio paths in both stages.

Deployment requires updating the stored agent prompt to use the plain script command above and remove the former receipt requirement and sync-mode flag. Do not merge, change the live prompt, or rerun the automation until the operator approves the replacement. Private source values and runtime logs remain outside the repository.

## Verify and deploy

Run focused and full tests plus `git diff --check` and `python3 scripts/check_repo_privacy.py`. After merge, privately dry-run the configured gids and verify Main-only counts, exact values, reported cash, same-day order, closed-position history, watchlist isolation, and malformed-source behavior before enabling scheduled sync. Do not use live sources during repository tests.
