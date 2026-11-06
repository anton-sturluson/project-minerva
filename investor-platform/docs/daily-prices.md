# Daily prices

The private web app can collect prices every day at **17:00 America/New_York**. The schedule follows Eastern daylight saving time and runs in the API process, without an open browser or an external agent. PostgreSQL stores validated histories and collection status; no transaction, holding quantity or cash balance is changed.

## Enable

The canonical `investor-platform/scripts/run-tailscale.sh` launcher applies migrations, builds the web app and records the Git release. Daily collection remains opt-in: set this in the ignored backend `.env` or export it before starting the private API. Exported variables take precedence over `.env`:

```dotenv
INVESTOR_DAILY_PRICES=1
```

The worker is only enabled in `INVESTOR_MODE=tailscale`; synthetic local development servers do not run it. Keep the host awake and the API, PostgreSQL and network running. This option does not configure operating-system auto-start or prevent sleep. Existing [Tailscale startup instructions](tailscale.md) still apply after a host reboot.

At startup the worker catches up the most recent scheduled collection if needed. Successful runs are remembered across restarts. A PostgreSQL lock prevents two API processes from collecting the same workspace concurrently. Each attempt is committed as `running` before provider requests. If the process stops during collection, that attempt remains visible and counts toward the retry limit. Failed or late-provider runs are retried after 30 minutes, at most three attempts per scheduled day. A database outage is retried after 30 minutes. After an extended outage, one refresh downloads the covered history; missed daily jobs are not individually replayed.

## Data and freshness

Each USD account is processed separately. The collector warms histories needed for all recorded holding periods, SPY and QQQ, plus foreign prices and dated currency conversions. Closed positions only request the dates on which they were held. Empty or non-USD accounts are skipped. Current holdings are collected first; each historical listing window then succeeds or fails independently. An unavailable sold listing cannot prevent current prices or other listing windows from updating. Provider failures do not stop collection for other accounts and never replace a good cache with a failed response.

Every scheduled attempt requests data newer than the attempt start, replacing accepted stored prices when a validated response is available. Normal reads reuse validated stored data that covers their dates; uncovered dates still require acquisition. Requests sharing a symbol and covered range reuse the attempt's fresh result. History is downloaded again because providers may revise past adjusted prices and corporate actions; this is a replaceable cache, not an immutable pricing archive.

5 p.m. is the collection start, not a provider publication guarantee. Weekends and holidays retain actual prior closing dates; no synthetic closes are created. If a weekday's SPY/QQQ close has not arrived, status is `awaiting_close` and bounded retries apply (including holidays). Missing same-date FX or a missing latest benchmark-session price for an open holding triggers a retry. A successful request can still contain a prior local-market close carried across a foreign exchange holiday: the normal freshness, currency, missing-session and split safeguards remain in force.

Holdings and the chart date controls permit today's data after 5 p.m. New York. Before then they end at yesterday. Reload data rereads accepted prices across the account panels and collection status. Returning to the page after the cutoff advances date ranges that follow the latest close; explicitly selected historical ranges stay fixed. The page does not poll or force provider downloads. Browser/API response times benefit from the [shared private cache](operations.md#historical-data-fallback).

## Status and manual retry

The authenticated `/api/market-data/status` endpoint reports whether the worker is enabled and alive, loaded release, last attempt, last complete success, next due time, and per-symbol current/history failures. It does not contact providers. Failures use stable reason codes; provider responses, account names and connection details are excluded. A partial run retains the prior complete-success timestamp. `/api/health` also identifies the loaded release.

From `investor-platform/backend`, select the same `DATABASE_URL` used by the private API, then run:

```sh
uv run --frozen investor-refresh-prices --status
uv run --frozen investor-refresh-prices --force
```

The CLI loads `.env` and respects exported environment variables. Omitting `--force` runs only when collection is due; `--status` never downloads. Before 5 p.m. these commands target the previous scheduled day's completed prices. Output contains the scheduled date, attempt count, collected/skipped/failed account counts and oldest latest benchmark close. `partial` returns exit code 1; provider error bodies and account identities are not printed. Detailed run state lives in `price_refresh_runs`, scoped to the local workspace.
