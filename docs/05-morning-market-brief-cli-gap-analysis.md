# Morning Market Brief — V1 Implementation Plan

Date: 2026-04-08
Status: deterministic evidence pipeline implemented; final note-generation step still pending

## Goal

Implement a v1 morning-brief pipeline where:
- Minerva CLI manages portfolio state and collects structured daily evidence
- Minerva CLI prepares an agent-ready evidence pack
- Charlie (main agent) writes the actual morning brief and Slack distillation
- the existing scheduled job uses these commands instead of doing the whole job in one prompt

## V1 scope

Implement these commands in v1:
- `minerva portfolio sync`
- `minerva portfolio adjacency`
- `minerva portfolio thesis`
- `minerva brief filings`
- `minerva brief earnings`
- `minerva brief macro`
- `minerva brief ir`
- `minerva brief market`
- `minerva brief prep`
- `minerva brief audit`
- `minerva brief review-log`

V1 also includes:
- manifest writing
- deterministic evidence renders
- cron/scheduler update to run the commands in sequence before the main-agent writeup

## Out of scope for v1

- first-class `brief news` CLI command for Reuters/newswire collection
- automatic IR URL discovery
- automatic adjacency discovery/refresh
- bidirectional writes back into the Google Sheet
- replacing the main agent’s analysis with deterministic scoring

## Current implementation status

As of 2026-04-09, the deterministic harness surface exists and is fixture-tested:
- `portfolio sync`
- `portfolio adjacency` (`list`, `add`, `remove`, `render`)
- `portfolio thesis` (`list`, `show`, `set`, `render`)
- `brief filings`, `earnings`, `macro`, `ir`, `market`, `prep`, `audit`, `review-log`
- `scripts/run_morning_brief_v1.sh`

What is true right now:
- the harness collects and normalizes evidence into raw, structured, and rendered artifacts
- the wrapper script performs the deterministic collection flow and enforces a manifest status gate before post-write steps continue
- the note files are created at the expected locations, but they are still seeded with placeholder text (`Pending main-agent writeup.`)

So the remaining functional gap is not collection. It is the final write stage that turns prepared evidence into a real `morning-brief-report.md` and `slack-brief.md`.

---

## Storage layout

### Portfolio state

```text
hard-disk/data/portfolio/
├── INDEX.md
├── current/
│   ├── INDEX.md
│   ├── holdings.json
│   ├── watchlist.json
│   ├── universe.json
│   ├── adjacent-map.json
│   ├── thesis-cards.json
│   ├── ir-registry.json
│   └── rendered.md
├── history/
│   ├── INDEX.md
│   ├── sync-log.jsonl
│   ├── universe-history.jsonl
│   ├── metadata-history.jsonl
│   └── rendered-history.md
└── transactions.json
```

Notes:
- `portfolio/`, `current/`, and `history/` should be indexed
- watchlist is local-only for now and can start empty
- `transactions.json` is the single general ledger file
- history should be compact log-based history, not a full dated snapshot every day

### Daily morning run artifacts

```text
hard-disk/reports/daily-news/
├── INDEX.md
├── 2026-04-08/
│   ├── notes/
│   │   ├── morning-brief-report.md
│   │   └── slack-brief.md
│   ├── data/
│   │   ├── raw/
│   │   │   ├── filings.json
│   │   │   ├── earnings.json
│   │   │   ├── macro.json
│   │   │   ├── ir.json
│   │   │   ├── market.json
│   │   │   └── manifest.json
│   │   ├── structured/
│   │   │   ├── universe.json
│   │   │   ├── prepared-evidence.json
│   │   │   └── audit.json
│   │   └── rendered/
│   │       ├── evidence.md
│   │       ├── grouped-events.md
│   │       ├── audit.md
│   │       └── source-status.md
│   └── INDEX.md
├── review-log.jsonl
└── ...
```

Notes:
- `daily-news/` should be indexed
- raw outputs are JSON
- prepared outputs are JSON
- rendered support files are markdown
- the actual narrative brief is intended to live in `notes/`
- current code seeds placeholder note files there until the main-agent write step is wired in

---

## Current command surface

## Portfolio namespace

### `minerva portfolio sync`
Purpose:
- pull holdings and transactions from the Google Sheet
- merge with a locally managed watchlist
- update `current/` portfolio state
- append compact history entries
- render a markdown summary

Inputs:
- sheet identifier / config
- holdings tab
- transactions tab
- local watchlist file
- optional `--date` or `--as-of`

Writes:
- `current/holdings.json`
- `current/watchlist.json`
- `current/universe.json`
- `transactions.json`
- history log files under `history/`
- `current/rendered.md`

Implementation details:
- watchlist is local-only for v1; start with an empty file if needed
- normalize each security to a canonical identifier
- compute `universe.json` as holdings + watchlist
- append change records to history logs instead of writing full dated snapshots
- render markdown after each sync so the current state is easy to inspect

### `minerva portfolio adjacency`
Purpose:
- manage the curated adjacent-company map stored locally

Subcommands:
- `list` — show all stored adjacency mappings
- `add` — add one adjacency relationship
- `remove` — delete one adjacency relationship
- `render` — render the adjacency map as markdown

Writes:
- `current/adjacent-map.json`
- optional history entry
- rendered adjacency markdown

Implementation details:
- store adjacency locally for now
- each mapping should include:
  - monitored company
  - adjacent company
  - relationship type
  - optional note / priority
- keep this human-curated in v1

### `minerva portfolio thesis`
Purpose:
- manage compact thesis cards per monitored security

Subcommands:
- `list` — list securities with thesis cards
- `show` — show one thesis card
- `set` — create or replace one thesis card
- `render` — render all thesis cards as markdown

Writes:
- `current/thesis-cards.json`
- optional history entry
- rendered thesis markdown

Implementation details:
- thesis cards should be compact, not full reports
- likely fields:
  - security identifier
  - thesis summary
  - key expectations
  - disconfirming signals
  - updated timestamp

## Brief namespace

### `minerva brief filings`
Purpose:
- collect overnight SEC filings for the monitored universe
- filter to material forms
- normalize them into event rows

Inputs:
- `universe.json`
- form allowlist / denylist
- `--date` or `--since` / `--until`

Writes:
- raw filings JSON
- normalized filings event JSON
- optional rendered markdown list

Implementation details:
- this must reuse existing `sec` primitives
- `sec` remains the low-level ticker/document namespace
- `brief filings` is the watchlist-wide orchestration layer on top of `sec`
- do not duplicate SEC retrieval logic

### `minerva brief earnings`
Purpose:
- collect reported and upcoming earnings for monitored names
- include adjacent names with strong read-through value
- include non-adjacent names only when clearly market-relevant

Inputs:
- `universe.json`
- adjacency map
- `--date` or date window

Proposed v1 source:
- use one configured market-data provider for earnings metadata; recommendation: start with a single provider such as Finnhub so `brief earnings` and `brief market` share the same provider layer

Writes:
- raw earnings source JSON
- normalized earnings events JSON
- optional rendered schedule/results markdown

Implementation details:
- normalize:
  - reported vs scheduled
  - before-open vs after-close vs unknown timing
  - monitored vs adjacent vs non-adjacent market-relevant
- this command collects metadata and references only; it does not do deep earnings analysis

### `minerva brief macro`
Purpose:
- collect the day’s macro / policy schedule in normalized form

Inputs:
- `--date` or run window

Proposed v1 sources:
- small curated list of official calendars/pages
- likely starting set: BLS, BEA, Census, Treasury, and Federal Reserve

Writes:
- raw macro JSON
- normalized macro events JSON
- optional rendered calendar markdown

Implementation details:
- keep the schema simple:
  - event name
  - release time
  - source
  - category
  - importance tag
- maintain the tracked macro-source list in a small local registry/config file

### `minerva brief ir`
Purpose:
- scan known IR / press-release pages for monitored names
- capture overnight releases and normalize them

Inputs:
- `universe.json`
- local IR registry
- `--date` or time window

Registry location:
- `hard-disk/data/portfolio/current/ir-registry.json`

Writes:
- raw IR scan JSON
- normalized IR release events JSON
- optional rendered markdown list

Implementation details:
- store IR URLs locally in v1
- populate the initial registry manually or semi-manually once per monitored company
- do not attempt automatic IR discovery in v1
- collect only titles, URLs, timestamps, and references here; deeper extraction is separate

### `minerva brief market`
Purpose:
- collect only the market context that is large or explanatory enough to matter

Inputs:
- `--date` or run window

Proposed v1 source:
- use the same configured market-data provider chosen for `brief earnings`; recommendation: start with one provider such as Finnhub so earnings and market share the same integration layer

Writes:
- raw market snapshot JSON
- normalized market-context JSON
- optional rendered markdown summary

Implementation details:
- keep this intentionally narrow
- collect only:
  - major index moves
  - rates / FX when material
  - other moves only when outsized or explanatory
- do not turn this into a generic dashboard dump

### `minerva brief prep`
Purpose:
- prepare a cleaner agent-ready evidence pack from collected raw inputs

Inputs:
- filings / earnings / macro / IR / market JSON
- `universe.json`
- adjacency map
- thesis cards

Writes:
- `prepared-evidence.json`
- `grouped-events.md`
- `source-status.md`
- optional suppression log

Implementation details:
- this is evidence hygiene, not final judgment
- do:
  - deduplication
  - relationship tagging
  - event-type tagging
  - stale/empty suppression
  - candidate section grouping
- do not try to replace the main agent’s prioritization

### `minerva brief audit`
Purpose:
- run a bounded cross-check for misses after prep

Inputs:
- prepared evidence
- manifest
- optional broader scan inputs

Writes:
- `audit.json`
- optional rendered audit markdown

Implementation details:
- keep this bounded
- this is a miss-check, not a second full brief pipeline

### `minerva brief review-log`
Purpose:
- append one structured review entry per daily-news run

Inputs:
- manifest from the just-completed run
- audit output from that same run, if present
- optional operator notes

Writes:
- `hard-disk/reports/daily-news/review-log.jsonl`

Implementation details:
- write one entry after each daily-news session
- this command mainly reads the current run’s manifest + audit output and appends one structured record
- capture:
  - run id/date
  - source failures
  - degraded modes used
  - misses found later
  - recurring collection pain points

---

## Daily run flow

The daily run should work like this:

1. `minerva portfolio sync`
2. `minerva brief filings`
3. `minerva brief earnings`
4. `minerva brief macro`
5. `minerva brief ir`
6. `minerva brief market`
7. `minerva brief prep`
8. Charlie reads the evidence pack and writes:
   - `notes/morning-brief-report.md`
   - `notes/slack-brief.md`
9. `minerva brief audit`
10. `minerva brief review-log`
11. OpenClaw posts the Slack brief

The important boundary is:
- CLI collects and prepares evidence
- Charlie writes the actual analysis

Current implementation note:
- steps 1 through 7, plus 9 and 10, are implemented in the harness
- step 8 is still an orchestration gap, which is why the current note files are placeholders instead of a finished brief

---

## Cron / scheduler update

The existing scheduled job should be updated so it no longer tries to do the entire morning brief in one agent prompt.

Instead, it should:
1. run the deterministic CLI commands first
2. hand the resulting evidence pack to Charlie
3. have Charlie write the morning brief and Slack brief
4. optionally run audit + review-log after that

## Recommended implementation pattern

Do **not** put a giant chain directly into the cron line.

Instead, create one thin wrapper script, for example:
- `scripts/run_morning_brief_v1.sh`

That script should:
1. derive the run date
2. create the daily run folder if needed
3. call the CLI commands in order
4. invoke the main-agent step using the prepared evidence path
5. append review logs
6. exit non-zero if the deterministic collection phase failed in a way that should block delivery

## Expected command sequence inside the wrapper

```bash
minerva portfolio sync --date "$RUN_DATE"
minerva brief filings --date "$RUN_DATE"
minerva brief earnings --date "$RUN_DATE"
minerva brief macro --date "$RUN_DATE"
minerva brief ir --date "$RUN_DATE"
minerva brief market --date "$RUN_DATE"
minerva brief prep --date "$RUN_DATE"
# main-agent writeup step happens here
minerva brief audit --date "$RUN_DATE"
minerva brief review-log --date "$RUN_DATE"
```

## Scheduler behavior change

Today’s job logic is effectively:
- scheduled prompt -> agent tries to do everything

V1 should become:
- scheduled trigger -> wrapper script / orchestrator -> deterministic CLI collection -> main-agent writeup -> Slack delivery

That is the key operational change.

## Concrete cron migration plan

Because the schedule mechanism itself appears to live outside this repo, the safest migration is to change only the execution target, not to rebuild the schedule logic from scratch.

Recommended change:
1. keep the existing trigger time the same
2. replace the old one-shot prompt entrypoint with a call to `scripts/run_morning_brief_v1.sh`
3. pass any required source/registry environment variables in the cron environment or a sourced env file
4. have the scheduled orchestration layer wait for `prepared_evidence` + `manifest` from the wrapper, then invoke Charlie for the write step
5. only after the write step succeeds, run `brief audit` and `brief review-log` if they are not already folded into the orchestration wrapper

Recommended cron-owned responsibilities:
- set a stable working directory
- export `UV_CACHE_DIR`
- export `MINERVA_WORKSPACE_ROOT`
- export any provider/source/registry env vars
- call the wrapper script with the run date
- capture stdout/stderr to a dated log file
- alert on non-zero exit

Recommended wrapper-owned responsibilities:
- portfolio sync
- deterministic evidence collection
- manifest status gating
- printing the exact `prepared_evidence` and `manifest` paths for the next orchestrator step

Recommended agent/orchestrator responsibilities:
- read `prepared-evidence.json`
- write `notes/morning-brief-report.md`
- write `notes/slack-brief.md`
- deliver the Slack brief

In other words, cron should trigger the harness, not impersonate the analyst.

---

## Build order

Recommended implementation order:

1. `portfolio sync`
2. `portfolio adjacency`
3. `portfolio thesis`
4. `brief filings`
5. `brief earnings`
6. `brief macro`
7. `brief ir`
8. `brief market`
9. `brief prep`
10. manifest writing + rendered evidence files
11. `brief audit`
12. `brief review-log`
13. scheduler/wrapper update

This order gets the evidence pipeline working before the cron integration depends on it.
