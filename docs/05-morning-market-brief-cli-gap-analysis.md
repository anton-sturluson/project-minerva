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
- `minerva brief macro-collect`
- `minerva brief macro`
- `minerva brief ir`
- `minerva brief market`
- `minerva brief prep`

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
hard-disk/data/01-portfolio/
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
hard-disk/reports/03-daily-news/
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

Uses LLM:
- no

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

Exact behavior:
- read the latest portfolio inputs
- normalize identifiers and merge holdings plus watchlist into the current universe
- persist the current state and append compact history records
- render a human-readable current portfolio summary

Implementation details:
- watchlist is local-only for v1; start with an empty file if needed
- normalize each security to a canonical identifier
- compute `universe.json` as holdings + watchlist
- append change records to history logs instead of writing full dated snapshots
- render markdown after each sync so the current state is easy to inspect

### `minerva portfolio adjacency`
Purpose:
- manage the curated adjacent-company map stored locally

Uses LLM:
- no in v1

Subcommands:
- `list` — show all stored adjacency mappings
- `add` — add one adjacency relationship
- `remove` — delete one adjacency relationship
- `render` — render the adjacency map as markdown

Writes:
- `current/adjacent-map.json`
- optional history entry
- rendered adjacency markdown

Exact behavior:
- persist the locally curated read-through map for monitored names
- let operators add, remove, inspect, and render adjacency relationships
- make that map available to the brief pipeline for relationship tagging

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

Uses LLM:
- no for storage and rendering; thesis content itself may be human-written or model-assisted upstream, but this command is just the persistence layer

Subcommands:
- `list` — list securities with thesis cards
- `show` — show one thesis card
- `set` — create or replace one thesis card
- `render` — render all thesis cards as markdown

Writes:
- `current/thesis-cards.json`
- optional history entry
- rendered thesis markdown

Exact behavior:
- store, replace, inspect, and render compact thesis cards for the monitored universe
- make those cards available to the writing and prep stages as lightweight context
- avoid turning thesis storage into a report-generation step

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

Uses LLM:
- no

Inputs:
- `universe.json`
- form allowlist / denylist
- `--date` or `--since` / `--until`

Writes:
- raw filings JSON
- normalized filings event JSON
- optional rendered markdown list

Exact behavior:
- read the monitored universe
- fetch qualifying filings, or load them from a supplied source file
- write one normalized event row per relevant filing with date, form, issuer, headline, and URL
- update manifest status for the filings source

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

Uses LLM:
- no

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

Exact behavior:
- read earnings metadata from the chosen provider or a supplied source file
- normalize timing and relationship tags
- keep metadata and references only, without attempting deeper earnings analysis
- update manifest status for the earnings source

Implementation details:
- normalize:
  - reported vs scheduled
  - before-open vs after-close vs unknown timing
  - monitored vs adjacent vs non-adjacent market-relevant
- this command collects metadata and references only; it does not do deep earnings analysis

### `minerva brief macro-collect`
Purpose:
- build the normalized macro source file from the local macro registry

Uses LLM:
- no

Inputs:
- `--date` or run window
- `macro-registry.json`
- optional explicit output path

Writes:
- generated `macro-events.json`
- source-level status metadata for the manifest

Exact behavior:
- read the curated official-source list from the macro registry
- fetch and parse those sources deterministically
- emit one normalized `macro-events.json` payload for the run date
- record per-source success/degraded status for the manifest

Implementation details:
- this is the missing bridge between the registry and the existing macro ingestion step
- it reads the curated official-source list, parses those sources, and writes one normalized payload the rest of the pipeline can consume
- if no macro source file is supplied to the wrapper, this command should run first and generate one deterministically
- this command does *not* replace `brief macro`; it feeds it

### `minerva brief macro`
Purpose:
- ingest the day’s macro / policy schedule in normalized form

Uses LLM:
- no

Inputs:
- `--date` or run window
- a prepared `macro-events.json` source, either passed directly or generated by `brief macro-collect`

Proposed v1 sources:
- small curated list of official calendars/pages
- likely starting set: BLS, BEA, Census, Treasury, and Federal Reserve

Writes:
- raw macro JSON
- normalized macro events JSON
- optional rendered calendar markdown

Exact behavior:
- read the prepared macro events payload
- keep the events that match the run date
- normalize them into the shared brief-event schema
- write raw, normalized, and rendered macro outputs
- update manifest status for the macro source

Implementation details:
- keep the schema simple:
  - event name
  - release time
  - source
  - category
  - importance tag
- maintain the tracked macro-source list in a small local registry/config file
- important distinction:
  - `brief macro-collect` is the *builder*
  - `brief macro` is the *consumer / ingester*
  - before this change, the pipeline could only use a macro source file if one already existed
  - after this change, the harness can generate that file itself from the registry and then ingest it

### `minerva brief ir`
Purpose:
- scan known IR / press-release pages for monitored names
- capture overnight releases and normalize them

Uses LLM:
- no in v1

Inputs:
- `universe.json`
- local IR registry
- `--date` or time window

Registry location:
- `hard-disk/data/01-portfolio/current/ir-registry.json`

Writes:
- raw IR scan JSON
- normalized IR release events JSON
- optional rendered markdown list

Exact behavior:
- read the locally curated IR registry
- fetch each configured feed or page
- extract overnight titles, URLs, dates, and issuer mapping into normalized events
- update manifest status for the IR source

Implementation details:
- store IR URLs locally in v1
- populate the initial registry manually or semi-manually once per monitored company
- do not attempt automatic IR discovery in v1
- collect only titles, URLs, timestamps, and references here; deeper extraction is separate

### `minerva brief market`
Purpose:
- collect only the market context that is large or explanatory enough to matter

Uses LLM:
- no

Inputs:
- `--date` or run window

Proposed v1 source:
- use the same configured market-data provider chosen for `brief earnings`; recommendation: start with one provider such as Finnhub so earnings and market share the same integration layer

Writes:
- raw market snapshot JSON
- normalized market-context JSON
- optional rendered markdown summary

Exact behavior:
- read market context from the chosen provider or a supplied source file
- keep only material index, rates, FX, or other explanatory moves
- normalize those into the shared brief-event schema
- update manifest status for the market source

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

Uses LLM:
- no

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

Exact behavior:
- combine all collected source events into one evidence pack
- deduplicate, relationship-tag, and group them for the writing step
- suppress stale, empty, or duplicate events
- produce the compact writer-facing artifacts without making final editorial judgments

Implementation details:
- this is evidence hygiene, not final judgment
- do:
  - deduplication
  - relationship tagging
  - event-type tagging
  - stale/empty suppression
  - candidate section grouping
- `grouped-events.md` and `source-status.md` should be Charlie’s default entry point; raw source files are for drill-down, not first read
- do not try to replace the main agent’s prioritization

---

## Charlie's Autonomous Planning & Writing

After the deterministic pipeline finishes at `brief prep`, Charlie takes the driver's seat.

Purpose:
- decide which events require deep dives
- extract answers from raw sources without blowing up the context window
- write the final reports

Uses LLM:
- yes (this is Charlie himself, operating autonomously)

Inputs:
- `grouped-events.md`
- `source-status.md`
- `prepared-evidence.json` (as reference)

Writes:
- `reports/03-daily-news/<date>/notes/execution-plan.md`
- `reports/03-daily-news/<date>/notes/morning-brief-report.md`
- `reports/03-daily-news/<date>/notes/slack-brief.md`

Exact behavior:
1. **Audit & Plan**: Charlie reads the collected headlines and the source status, decides whether the evidence is sufficient, and writes an `execution-plan.md` containing targeted questions or angles needed for the specific events that actually matter.
2. **Targeted Extraction**: Charlie uses `minerva extract` / `extract-many` (e.g. `--model openai/gpt-5.4`) against massive raw SEC/IR files to answer his planned questions. This keeps his working context strictly focused on signal instead of noise.
3. **Synthesis**: Charlie writes the final reports based on the extracted answers.

Implementation details:
- this completely replaces the old idea of having `brief audit` or `brief plan` as rigid CLI pipeline commands
- the pipeline's job ends at `brief prep`, and Charlie's job begins by reading the summary artifacts

---

## LLM boundary and context management

The intended boundary in v1 is:
- `portfolio ...` commands are deterministic state management
- `brief filings`, `earnings`, `macro-collect`, `macro`, `ir`, `market`, and `prep` are strictly deterministic evidence collection and preparation
- the pipeline halts at `brief prep`, handing off to Charlie
- Charlie takes the driver's seat: he audits the evidence, creates a plan, reads deep sources via targeted extraction, and writes the brief

In practice, that means:
- zero LLM usage happens during the automated collection phase itself
- `brief prep` compresses and groups the collected evidence before Charlie sees it
- Charlie wakes up and starts from `grouped-events.md` and `source-status.md`
- Charlie determines his own audit verdict and reading plan
- to read the full text of SEC filings or press releases, Charlie uses `minerva extract` or `minerva extract-many` (e.g. `--model openai/gpt-5.4`) to ask targeted questions, rather than pulling the entire document into context. This prevents context bloat and keeps his working session strictly focused on signal instead of noise.

---

## Daily run flow

The daily run should work like this:

1. `minerva portfolio sync`
2. `minerva brief filings`
3. `minerva brief earnings`
4. `minerva brief macro-collect`
5. `minerva brief macro`
6. `minerva brief ir`
7. `minerva brief market`
8. `minerva brief prep`
9. Charlie wakes up, reads `grouped-events.md` and `source-status.md`, and takes over as the autonomous intelligence layer:
   - he decides whether to audit the evidence pack or request more data
   - he builds his own execution plan
   - he uses `minerva extract` / `extract-many` to deep dive on the full sources without blowing up his context window
   - he runs `minerva brief audit` to validate the evidence pack before writing; if the audit fails, he loops back to collect or extract more data until the evidence passes
   - once the audit passes, he writes `notes/morning-brief-report.md` and `notes/slack-brief.md`
10. OpenClaw posts the Slack brief

The important boundary is:
- CLI deterministically collects and prepares the initial evidence pack (steps 1-8)
- Charlie is in the driver's seat for everything else: auditing, planning, targeted extraction, and writing (step 9)

---

## Cron / scheduler update

The wrapper script (`scripts/run_morning_brief_v1.sh`) runs steps 1-8 deterministically.

Expected command sequence inside the wrapper:

```
minerva portfolio sync --date "$RUN_DATE"
minerva brief filings --date "$RUN_DATE"
minerva brief earnings --date "$RUN_DATE"
minerva brief macro-collect --date "$RUN_DATE"
minerva brief macro --date "$RUN_DATE"
minerva brief ir --date "$RUN_DATE"
minerva brief market --date "$RUN_DATE"
minerva brief prep --date "$RUN_DATE"
# The deterministic pipeline ends here.
# Charlie wakes up, reads the prepared evidence, and takes the driver's seat.
```

After the wrapper completes, the scheduler should wake Charlie to take over.

---

## Build order

Recommended implementation order:

1. `portfolio sync`
2. `portfolio adjacency`
3. `portfolio thesis`
4. `brief filings`
5. `brief earnings`
6. `brief macro-collect`
7. `brief macro`
8. `brief ir`
9. `brief market`
10. `brief prep`
11. manifest writing + rendered evidence files
12. scheduler/wrapper update
13. Charlie autonomous prompt/wake configuration

This order gets the evidence pipeline working before the cron integration depends on it.

---

## Portfolio Sync — CSV Header Normalization & Exchange Column

Date added: 2026-04-14

### Problem

The Google Sheet CSV headers use mixed case and human-readable names (e.g. `Ticker`, `# Shares`, `Year of Purcase`, `% Change`). When `portfolio sync` loads holdings from the Google Sheet via CSV export, `csv.DictReader` uses these exact headers as dict keys. But `_normalize_security_row` expects lowercase snake_case keys (`ticker`, `shares`, `exchange`). This means:

- Fresh syncs from the sheet silently produce empty records (all fields blank) because no keys match
- The pipeline has been working only because it falls back to loading the already-processed `holdings.json` with lowercase keys when `--sheet-id` is not passed
- The new `Exchange` column will not flow through to enrichment or downstream consumers without a header normalization step

### Current Google Sheet headers

| CSV Header | Target key | Notes |
|-----------|-----------|-------|
| `Ticker` | `ticker` | Primary identifier |
| `Category` | `category` | Sector/type label |
| `Year of Purcase` | `year_of_purchase` | Typo in sheet; normalize anyway |
| `Cost` | `cost` | Per-share cost |
| `# Shares` | `shares` | Position size |
| `Total Cost` | `total_cost` | |
| `Price` | `price` | Current price |
| `Market Value` | `market_value` | |
| `% Change` | `pct_change` | |
| `Net` | `net` | |
| `CAGR` | `cagr` | |
| `% Portfolio (Value-based)` | `weight` | Map to existing weight field |
| `% Portfolio (Cost-based)` | `cost_weight` | |
| `Target % (Value-based)` | `target_weight` | |
| `Target diff` | `target_diff` | |
| `CAGR Target` | `cagr_target` | |
| `Price Target` | `price_target` | |
| `Target Year` | `target_year` | |
| `Exchange` | `exchange` | *New column* — ASX, TSXV, etc. Blank for US tickers |

### Implementation steps

1. **Add `_normalize_csv_headers` function** in `portfolio_state.py`:
   - Accept a list of dicts (CSV rows) and return a new list with normalized keys
   - Normalize: strip whitespace, lowercase, replace spaces/special chars with underscores
   - Apply explicit mappings for known columns:
     - `ticker` → `ticker`
     - `# shares` → `shares`
     - `% portfolio\n(value-based)` or `% portfolio (value-based)` → `weight`
     - `year of purcase` → `year_of_purchase` (handle typo)
     - `exchange` → `exchange`
   - For any unmapped header, apply the generic normalize (lowercase + underscore)

2. **Call `_normalize_csv_headers` in `load_tabular_rows`**:
   - After loading CSV rows via `DictReader`, normalize the header keys before returning
   - Only apply to CSV sources (not JSON, which already has correct keys)

3. **Carry forward enrichment data during sync**:
   - When `portfolio sync` runs with a sheet source, the CSV will have the Exchange column but NOT `country`, `sec_registered`, or `finnhub_symbol` (those come from enrichment)
   - After normalizing and creating new records, merge any existing enrichment fields from the previous `holdings.json` so they aren't lost
   - Fields to carry forward: `exchange` (prefer sheet value if present, else keep existing), `country`, `sec_registered`, `finnhub_symbol`

4. **Update filings collector**:
   - Also skip non-security rows (CASH, TOTAL, CURRENT ASSET, etc.) in the filings collector, same as we already do in enrichment

5. **Tests**:
   - Test CSV header normalization with the exact Google Sheet headers
   - Test that Exchange column flows through sync → universe → enrichment
   - Test that enrichment data is preserved across re-syncs
   - Test filings collector skips non-security rows
