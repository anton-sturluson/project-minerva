# Evidence V2 Quickstart

## Overview

The V2 evidence workflow is **ledger-driven**: every source — SEC filing, industry report, news article — is recorded as a single line in `data/evidence.jsonl`. The ledger is the single source of truth for audit and downstream analysis. There are no YAML coverage profiles; recognized categories are defined in `src/harness/workflows/evidence/constants.py`.

The three public entry-points are `init`, `add-source`, and `audit`.

The evidence workflow stops at a verified evidence base. It does **not** write the final investment analysis for you. Use it to create the company tree, persist sources, and produce an audit memo that says whether the evidence is strong enough to support serious synthesis.

---

## Workspace layout after `init`

```
<company-root>/
├── data/
│   ├── evidence.jsonl       # V2 ledger (append-only, one JSON line per source)
│   ├── evidence.md          # Human-readable render of the ledger
│   ├── sources/             # Downloaded SEC filings and other files
│   │   ├── 10-K/
│   │   │   └── 2025-02-18/  # Per-section directory (one .md per Item)
│   │   │       ├── 01-business.md
│   │   │       ├── 07-mdna.md
│   │   │       └── ...
│   │   ├── 10-Q/
│   │   ├── earnings/
│   │   └── financials/
│   ├── references/          # Manually saved external PDFs, reports, etc.
│   └── meta/                # Workflow metadata and generated summaries
├── audits/                  # Audit memos (audit-YYYY-MM-DD.md)
├── plans/                   # Research plans and notes
├── research/                # Open-web research outputs and discovery notes
└── analysis/                # Human/agent synthesis, valuation outputs, draft analysis
```

`research/` is for discovery material: web research outputs, search notes, market maps, and other inputs that may become evidence. `analysis/` is for judgment work: thesis drafts, valuation outputs, memos, and final synthesis. Do not treat something as analysis just because it came from a research tool; analysis starts when the evidence is interpreted.

---

## Core commands

### `minerva evidence init`

Creates the directory tree and initializes a blank ledger for a company.

```bash
minerva evidence init \
  --root hard-disk/reports/00-companies/12-robinhood \
  --ticker HOOD \
  --name Robinhood \
  --slug robinhood
```

Run once per company. Safe to re-run — existing files are not overwritten.

---

### `minerva evidence add-source`

Registers any evidence source (SEC, report, article) in the V2 ledger.

```bash
# Register a downloaded industry report
minerva evidence add-source \
  --root hard-disk/reports/00-companies/12-robinhood \
  --title "Nilson Report 2025 — Payments Industry" \
  --category industry-report \
  --status downloaded \
  --path hard-disk/reports/00-companies/12-robinhood/data/references/nilson-2025.pdf \
  --url https://nilsonreport.com/reports/2025 \
  --notes "Useful for payments industry sizing and card-volume context."

# Register a discovered (not yet downloaded) competitor filing
minerva evidence add-source \
  --root hard-disk/reports/00-companies/12-robinhood \
  --title "Webull 10-K FY2024" \
  --category competitor-data \
  --status discovered \
  --url https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=webull \
  --notes "Potential competitor filing; download before relying on it."
```

**Recognized categories** (from `constants.py`):

| Category | Description |
|---|---|
| `sec-annual` | 10-K annual reports |
| `sec-quarterly` | 10-Q quarterly reports |
| `sec-earnings` | 8-K earnings releases |
| `sec-financials` | Structured financial statements |
| `sec-proxy` | DEF 14A proxy statements |
| `sec-other` | Other SEC filings |
| `industry-report` | Third-party market research |
| `competitor-data` | Competitor filings, press releases |
| `customer-evidence` | Customer surveys, reviews |
| `expert-input` | Analyst notes, channel checks |
| `news` | News articles |
| `company-ir` | IR presentations, investor days |
| `regulatory` | Regulatory filings and orders |
| `other` | Anything else |

Valid status values: `downloaded`, `discovered`, `blocked`.

Useful optional fields:
- `--notes` — why the source matters, what it covers, or why it is blocked.
- `--date` — publication or filing date (`YYYY-MM-DD`).
- `--collector` — who or what collected it, e.g. `manual`, `parallel`, `sec`.
- `--url` — canonical source URL.

An unknown category emits a warning to stderr but still writes the ledger entry.

---

### `minerva evidence audit`

Runs a gap assessment against the current ledger and writes a memo to `audits/audit-YYYY-MM-DD.md`. The LLM evaluates coverage across all categories and flags missing sources.

```bash
minerva evidence audit \
  --root hard-disk/reports/00-companies/12-robinhood
```

Optional flags:
- `--categories sec-annual,sec-quarterly` — scope the audit to specific categories
- `--model gpt-5.5` — override the model (default: `gpt-5.5`)
- `--api-key-env-var OPENAI_API_KEY` — env var containing the API key

The audit memo is the readiness signal for downstream analysis. If the memo says coverage is thin, collect or save more sources, register them with `add-source`, and rerun `audit`.

---

## Related commands

### `minerva research`

Runs deep open-web research through Parallel.ai. Use it when you need discovery outside the sources already saved in the evidence tree: market structure, competitors, regulatory background, channel checks, or source leads.

```bash
minerva research "Robinhood payment for order flow regulatory risk 2024 2025" \
  --output hard-disk/reports/00-companies/12-robinhood/research/pfof-regulatory-risk.md
```

Research output is not automatically evidence. If the output itself is useful, save it under `research/` and register it with `add-source`. If it points to better primary sources, download those sources into `data/sources/` or `data/references/` and register those instead.

### `minerva extract` / `minerva extract-many`

Runs targeted LLM extraction over a saved file. Use this after a source exists on disk and you need specific facts pulled out of it.

```bash
minerva extract "What revenue drivers and risks does management emphasize?" \
  --file hard-disk/reports/00-companies/12-robinhood/data/sources/10-K/2025-02-18/07-mdna.md
```

Extraction is a way to structure evidence; it is not a substitute for registering the underlying source in the ledger.

### `minerva analyze`

Runs deterministic text analysis such as n-grams and topic clustering.

```bash
minerva analyze ngrams hard-disk/reports/00-companies/12-robinhood/data/sources/10-K/2025-02-18/01-business.md \
  --top 20 --min-count 3
```

`analyze` is mechanical text analysis. It is useful for finding repeated terms, themes, and document structure. It is not the same thing as investment analysis.

---

## Typical workflow

```bash
# 1. Initialize the workspace
minerva evidence init --root .../12-robinhood --ticker HOOD --name Robinhood --slug robinhood

# 2. Add saved primary sources, filings, articles, and reports
minerva evidence add-source --root .../12-robinhood --title "Nilson Report" \
  --category industry-report --status downloaded --path .../nilson-2025.pdf

# 3. Use web research for discovery when the evidence base is thin
minerva research "Robinhood competitive position and payments economics" \
  --output .../12-robinhood/research/competitive-position.md

# 4. Register any durable research output or primary source it identifies
minerva evidence add-source --root .../12-robinhood --title "Competitive position research notes" \
  --category other --status downloaded --path .../12-robinhood/research/competitive-position.md

# 5. Run the evidence audit (LLM gap assessment)
minerva evidence audit --root .../12-robinhood

# 6. If the audit passes, move into human/agent synthesis under analysis/
```

---

## Research vs. analysis

- **Research** finds and preserves inputs: filings, transcripts, articles, reports, market maps, source leads, and extracted facts.
- **Analysis** makes judgments from those inputs: what matters, what is causal, what is noise, what the market is missing, what would change the thesis, and what the valuation implies.
- `minerva research` is a tool for discovery. It can produce useful notes, but those notes should still be saved and registered if they matter.
- `minerva analyze` is deterministic text analysis (`ngrams`, `topics`). It helps inspect documents, but it does not make investment judgments.
- There is currently no `minerva analysis status` or `minerva analysis context` command. The current readiness gate is `minerva evidence audit`; after that, write synthesis and valuation artifacts under `analysis/`.

## Notes

- Keep every durable source represented in `data/evidence.jsonl`; the ledger is the audit trail.
- Prefer primary sources over research summaries when both are available.
- A `discovered` ledger entry means “we know this source exists but do not have it yet.” A `downloaded` entry should point to a local file that exists.
- Research outputs are acceptable evidence when they are the actual artifact being relied on, but they are weaker than the primary documents they cite.
- If an audit memo identifies gaps, add or block the missing sources explicitly and rerun the audit before writing a confident thesis.
- Put final memos, valuation work, and thesis drafts in `analysis/`; put source discovery notes in `research/`.
