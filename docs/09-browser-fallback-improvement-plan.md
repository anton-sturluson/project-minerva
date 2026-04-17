# Browser Fallback for Blocked Web Sources — Improvement Plan

Date: 2026-04-15
Status: proposed

## Problem

The morning brief pipeline uses `requests` (plain HTTP) to fetch IR feeds, macro registry sources, and other web content. Several sites block these requests with Cloudflare JS challenges, bot protection, or aggressive WAFs. The result is 403 errors, read timeouts, or challenge pages instead of actual content.

### Blocked sources observed (2026-04-15 run)

| Source   | URL                                          | Failure Mode        |
|----------|----------------------------------------------|---------------------|
| IR/TSLA  | `ir.tesla.com/press`                         | 403 (entire domain) |
| IR/DUOL  | `investors.duolingo.com/press`               | Timeout (homepage works, press page doesn't) |
| IR/AVGO  | `investors.broadcom.com/rss-feeds`           | Timeout (homepage works, RSS page doesn't) |
| IR/COIN  | `investor.coinbase.com/news/default.aspx`    | 403 Cloudflare (entire domain) |
| IR/TSM   | `pr.tsmc.com/english/latest-news`            | 403 Cloudflare (entire domain) |
| Macro    | `www.bls.gov/schedule/`                      | 403 Forbidden       |

### Sites that work today but are at risk

Several IR pages (SPOT, OSCR, GOOGL) returned content on this run but are on platforms known to deploy Cloudflare intermittently. Any of them could start blocking tomorrow.

## Proposed Solution

Add a browser-based fallback *step* that runs after the HTTP collectors but before prep. The existing pipeline stays untouched. A subagent with the `browser` skill handles the blocked URLs.

### Updated pipeline flow

```
1.  portfolio sync
2.  brief filings
3.  brief earnings
4.  brief macro-collect
5.  brief macro
6.  brief ir
7.  brief market
    ──── all HTTP collection done ────
8.  CHECK MANIFEST for failures (new step)
9.  IF failures → SPAWN browser subagent (new step)
10. brief prep  (runs once, with both HTTP and browser results)
11. status check
```

Today the script runs steps 1–7 then goes straight to prep (step 10). The change inserts steps 8–9 between market and prep.

### How it work
1. After all HTTP collectors finish, read the manifest to identify failed tickers (status `error` or `degraded` with fetch errors)
2. For each failed ticker, look up the URL from the IR registry (or macro registry for macro failures)
3. Spawn a subagent with the `browser` skill. Give it:
   - The failed tickers and their registry URLs
   - The run date
   - What to extract: press release headlines, dates, and links published on the run date
   - The output path (e.g., `data/raw/ir-browser.json`)
4. The subagent navigates each site in the browser, handles Cloudflare challenges, and writes results in the same event JSON format the IR collector uses
5. `brief prep` runs once and merges both `ir.json` and `ir-browser.json` into the evidence pack

## What needs to change

### 1. Shell script: `run_morning_brief_v1.sh`

Insert a manifest check + browser fallback step between `brief market` and `brief prep`.

The script needs to:
- Read the manifest after all HTTP collectors finish
- Extract failed tickers and their registry URLs
- If failures exist, spawn the browser subagent via `openclaw agent` and wait for completion
- Then continue to `brief prep`

The subagent is spawned via `openclaw agent` CLI, which works the same whether called from a shell script, a cron job, or an agent session:

```bash
# After all HTTP collectors, check for IR failures
FAILED_TICKERS=$(uv run python - "${MANIFEST_PATH}" "${IR_REGISTRY_PATH}" <<'PY'
import json, sys
manifest = json.loads(open(sys.argv[1]).read())
registry = json.loads(open(sys.argv[2]).read())
ir = manifest.get("sources", {}).get("ir", {})
if ir.get("error_count", 0) == 0:
    sys.exit(0)
# Build list of failed tickers from ir.json errors
ir_raw = json.loads(open(manifest["sources"]["ir"]["raw_path"]).read())
failed = {e["security_id"]: e["url"] for e in ir_raw.get("errors", [])}
reg_lookup = {r["security_id"]: r["feeds"][0]["url"] for r in registry if r.get("feeds")}
for sid in failed:
    url = reg_lookup.get(sid, failed[sid])
    print(f"{sid}: {url}")
PY
)

if [[ -n "${FAILED_TICKERS}" ]]; then
  BROWSER_OUTPUT="${MINERVA_WORKSPACE_ROOT}/reports/03-daily-news/${RUN_DATE}/data/raw/ir-browser.json"
  openclaw agent \
    --agent main \
    --timeout 600 \
    --thinking medium \
    --message "Browser IR fallback for ${RUN_DATE}.

The following IR pages were blocked during HTTP collection. Use the browser skill to visit each page, find press releases or news items published on ${RUN_DATE}, and extract: headline, date, URL, and a brief summary of the content if visible.

Write the results as a JSON array of events to: ${BROWSER_OUTPUT}

Each event should have: source, event_type, event_date, security_id, headline, reference_url, and any additional metadata.

Failed tickers:
${FAILED_TICKERS}"
fi
```

This keeps the shell script as the orchestrator. `openclaw agent` blocks until the agent completes, so the script naturally waits before continuing to `brief prep`.

### 2. Prep command: `morning_brief.py` → `prepare_evidence()`

Small change: when loading raw IR data, also check for `ir-browser.json` in the same `data/raw/` directory. If it exists, merge its events into the IR event stream before deduplication and enrichment.

Same pattern for macro: if `macro-browser.json` exists, merge it.

The change is in the `_load_raw_source()` calls inside `prepare_evidence()` — extend the IR and macro loaders to union their events with any browser sidecar file.

### 3. OpenClaw cron job

The morning brief is triggered by an OpenClaw cron job:
- Job ID: `6f14f630-49f2-4440-bc3c-1b3464fa6b7f`
- Name: `Broad market morning brief`
- Agent: `main` (Charlie)
- Schedule: `0 4 * * *` (4am ET)
- Current timeout: `1800s` (30 minutes)
- Last run duration: ~264s (~4.4 minutes)
- Last run status: ok

Changes needed:
- **Timeout**: Currently 1800s, which is plenty of headroom. The browser fallback adds ~60-90s worst case (5-15s per blocked URL × ~6 blocked sources). No timeout change needed unless the number of blocked sources grows significantly.
- **Chrome requirement**: The `browser` skill requires Chrome to be running with the extension loaded. For a 4am automated job, Chrome must either already be running or the script needs to handle the case where it isn't (skip browser fallback, run in degraded mode as today).
- **Prompt update**: The cron job's existing prompt already includes a live supplement step (step 5) where the agent checks IR pages when inputs are degraded. Once the browser fallback is built into the shell script, that inline supplement becomes less critical for IR — the shell script handles it before the agent even starts writing. The prompt can be simplified accordingly.
- **Note**: The cron job currently runs on the `main` agent (Charlie). The `openclaw agent` call in the shell script can target any agent — we should decide whether the browser subagent runs as `main` or a dedicated agent.

### 4. What the subagent collects

The current HTTP-based IR collector only extracts listing-level data: headline, date, and URL. It never follows links to read the actual press release.

The browser subagent can do more. Since it's already on the page and navigating through Cloudflare, it can:
- Extract the listing data (headline, date, URL) — same as the HTTP path
- Click through to individual press releases and extract summaries or full text
- Capture metadata the HTML parser misses (e.g., event categories, related documents)

The prompt in section 1 above tells the agent to extract "headline, date, URL, and a brief summary of the content if visible." This gets us listing-level parity plus a content summary when the press release is accessible — strictly more than the HTTP path provides, without requiring the agent to read every full document.

No step-by-step browser instructions needed — the agent discovers the right approach per site.

## Current state of the IR registry

After today's additions, 17 of 18 universe securities have IR feed entries (VCSH excluded — it's a bond ETF with no IR page):

| Status         | Securities                                                        | Count |
| -------------- | ----------------------------------------------------------------- | ----- |
| Working (RSS)  | IMVT, LGCY, ACFN, HOOD                                            | 4     |
| Working (HTML) | TOI, KPG, AIM, GOOGL, SPOT, ZDC, OSCR, BEPC                       | 8     |
| Blocked        | TSLA (403), DUOL (timeout), AVGO (timeout), COIN (403), TSM (403) | 5     |
| N/A (ETF)      | VCSH                                                              | 1     |

The browser fallback would immediately unblock those 5, bringing IR coverage from ~65% to ~100% of the equity universe.

## Future considerations

- **Preemptive browser mode.** If a URL has failed via HTTP on the last N runs, skip the HTTP attempt and go straight to the browser subagent.
- **Parallel extraction.** Have the subagent open multiple browser tabs to reduce wall time.
- **Macro collectors.** Most macro sources have `collector_required` status — they need actual parsers, not just a fetch fix. The browser fallback helps with BLS (which is blocked) but the other 17 sources need parser work regardless.

## Notes

- The process for adding new securities to the IR registry is: find the IR/press-release page URL, determine format (RSS preferred, HTML fallback), and add an entry to `hard-disk/data/01-portfolio/current/ir-registry.json`. The securities must already be in the universe (via holdings or watchlist in portfolio sync).
- COIN, HOOD, and TSM were already in the universe as watchlist entries. They were just missing from the IR registry. Added 2026-04-15.
