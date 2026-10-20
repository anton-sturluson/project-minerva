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

The scheduler runs a fixed command, not a model-authored sync command:

```bash
./scripts/run_morning_brief_scheduled.sh --handoff-job "$CHILD_JOB_UUID"
```

1. The launcher requires the primary checkout on named branch `main` with no tracked or untracked changes. It fetches `origin/main`, fast-forwards only, then requires a clean checkout and `HEAD == origin/main`. It never stashes, resets, rebases, or repairs unexpected state. It uses that checkout's `uv` project and `.venv`.
2. The Python helper requires nonempty `MINERVA_PORTFOLIO_HOLDINGS_SOURCE` and `MINERVA_PORTFOLIO_TRANSACTIONS_SOURCE` from the inherited environment. It does not load shell startup files or construct source URLs. An optional `MINERVA_PORTFOLIO_WATCHLIST_SOURCE` overrides the existing local-watchlist fallback. No cached holdings/transactions fallback is allowed here.
3. Before each attempt, the helper deletes the previous receipt. After successful `minerva portfolio sync`, it writes version 1 of `portfolio-sync.receipt.json` in the daily `data/structured/news-pipeline/` directory. The receipt contains the requested date, UTC completion time, exact file hashes, and source fingerprints (not private URLs or input paths). Holdings, transactions, watchlist, and universe must still match, and the receipt must be no more than six hours old.
4. The helper calls `openclaw automations run "$CHILD_JOB_UUID" --json` once. Force is the CLI default, so the separately configured **disabled, agent-only** automation can run on demand. A successful process exit plus explicit enqueue admission and a run ID are required. **Queued is not completed.** There is no polling, sleep, retry, or child-completion claim. Success prints only `NO_REPLY` to avoid duplicate scheduler announcements.

The parent/operator must configure the scheduler and disabled child separately. This repository does not change automation configuration. Keep one scheduled producer; do not overlap pre-sync with another portfolio writer or a running consumer. The receipt checks the boundary, not concurrent writes after validation.

### Required child prompt instruction

> Determine `TODAY` in `America/New_York` and run `./scripts/run_morning_brief.sh "$TODAY" --use-synced-portfolio` from the main checkout. Consume only the already-synced Main-only portfolio. Never re-sync portfolio data, regenerate source URLs, or fall back to cached inputs if receipt validation fails. Stop and report the failure. Then follow the existing pipeline's synthesis handoff instructions.

The explicit flag validates the receipt **before any collection phase** and skips only portfolio sync. All other pipeline phases are unchanged. Calls without the flag retain their existing sync behavior. The producer and child must use the same workspace/report/artifact paths; receipt validation rejects a different `MINERVA_PORTFOLIO_UNIVERSE` path. Receipts do not require source configuration in the child.

### Verification and diagnostics

- `--date YYYY-MM-DD` selects the receipt/run date; the helper defaults to the current New York date. `--sync-only` replaces `--handoff-job` for controlled sync verification without an agent. It still requires configured sources and writes a receipt.
- `portfolio-sync.json`, `portfolio-sync.stderr.log`, and `portfolio-sync.status.json` retain the normal phase format. Kickoff output and status are separate `portfolio-handoff.*` artifacts. The consumer leaves the original sync status intact.
- Failures exit nonzero and show bounded diagnostics, using stdout when stderr is empty. A sync/source failure leaves no receipt. A kickoff failure retains the successful sync receipt but marks handoff failed; it does not mean that a child ran.
- These artifacts and normal sync history can contain private data. Keep them in existing ignored runtime storage, never in commits or public reports. The receipt uses SHA-256 for change detection, not as a signed authorization token.

## Verify and deploy

Run focused and full tests plus `git diff --check` and `python3 scripts/check_repo_privacy.py`. After merge, privately dry-run the configured gids and verify Main-only counts, exact values, reported cash, same-day order, closed-position history, watchlist isolation, and malformed-source behavior before enabling scheduled sync. Do not use live sources during repository tests.
