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

## Single-script daily flow

The scheduler runs one entry point with the existing final-writer job ID:

```bash
./scripts/run_morning_brief.sh "$SYNTHESIS_JOB_ID"
```

The script computes today's New York date, checks/fast-forwards clean main, and runs the existing portfolio sync from configured sources. It then performs the existing structured/news collection and evidence preparation. Its final command is `openclaw automations run "$SYNTHESIS_JOB_ID" --json`, after the prepared handoff is written and required checks pass. Sync or required-phase failure prevents that call. Existing browser/news collector agents remain part of collection; the final writing agent starts only at the end.

There is no second launcher, pre-sync Python helper, receipt, hash, expiry rule, or compatibility mode. The normal phase logs and existing synthesis handoff are reused. Missing source settings fail rather than silently using cached inputs. Only the script is scheduled; the final-writer job stays unscheduled and is explicitly invoked. Admission is not completion; that agent delivers the brief.

### Required final-writer prompt instruction

> Sync, collection, and preparation have already succeeded. Read today's existing `data/structured/news-pipeline/synthesis-handoff.json` in the dated daily-news report directory, then follow its versioned synthesis instructions and existing editorial overrides. Use the synced Main portfolio and collected evidence. Do not run the pipeline script, portfolio sync, or collection again. Return the completed brief through the existing delivery route.

### Deployment after explicit approval

Point the existing 04:00 New York command automation at the single script and final-writer job ID. It now includes collection, so use the existing one-hour run budget for both command and no-output timeouts, not the former ten-minute startup-only budget. Set command delivery to `none` (retain output in run history) and configure an explicit failure alert to the existing destination after the first failure. Keep the final writer's model and announcement destination unchanged; update its stored prompt to consume the prepared handoff without rerunning the script.

Do not merge, change live wiring/prompts, or rerun the automation until the operator approves. Keep one producer; do not independently invoke the writer or overlap portfolio writes. Private source values and runtime logs remain outside the repository.

## Verify and deploy

Run focused and full tests plus `git diff --check` and `python3 scripts/check_repo_privacy.py`. After merge, privately dry-run the configured gids and verify Main-only counts, exact values, reported cash, same-day order, closed-position history, watchlist isolation, and malformed-source behavior before enabling scheduled sync. Do not use live sources during repository tests.
