# Evidence V2 Quickstart

## Overview

The V2 evidence workflow is **ledger-driven**: every source — SEC filing, industry report, news article — is recorded as a single line in `data/evidence.jsonl`. The ledger is the single source of truth for inventory, audit, and analysis context. There are no YAML coverage profiles; all categories and extraction questions are defined in `src/harness/workflows/evidence/constants.py`.

The three public entry-points for daily use are `init`, `add-source`, and `audit`. The other commands (`collect sec`, `extract`, `inventory`, `migrate`) support specific steps of the pipeline.

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
│   └── meta/                # Inventory, SEC summary, extraction-runs/
├── audits/                  # Audit memos (audit-YYYY-MM-DD.md)
├── plans/                   # Research plans and notes
├── research/                # Scraped or downloaded research materials
└── analysis/                # Context manifests, status, valuation outputs
```

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
  --url https://nilsonreport.com/reports/2025

# Register a discovered (not yet downloaded) competitor filing
minerva evidence add-source \
  --root hard-disk/reports/00-companies/12-robinhood \
  --title "Webull 10-K FY2024" \
  --category competitor-data \
  --status discovered \
  --url https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=webull
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
- `--model gpt-4o` — override the model (default: `gpt-4o`)
- `--api-key-env-var OPENAI_API_KEY` — env var containing the API key

The audit memo is the primary readiness signal for `analysis status`.

---

## Other commands

### `minerva evidence collect sec`

Downloads SEC filings from EDGAR using edgartools. Writes per-section `.md` files under `data/sources/10-K/<date>/` and `data/sources/10-Q/<date>/`. Registers one ledger entry per logical filing directory.

```bash
minerva evidence collect sec \
  --root hard-disk/reports/00-companies/12-robinhood \
  --ticker HOOD \
  --annual 3 \
  --quarters 4 \
  --earnings 4
```

Optional flags:
- `--no-financials` — skip financial statement markdown/CSV
- `--no-html` — skip HTML rendering

**Per-section files**: edgartools extracts each Item (e.g., Item 1, Item 7, Item 7A) into a separate `.md` file. If structured access fails, the command falls back to a single-file download. HTML files are never written to the ledger.

**EDGAR identity**: set `EDGAR_COMPANY_NAME` and `EDGAR_EMAIL` environment variables, or configure them via `HarnessSettings`.

---

### `minerva evidence extract`

Runs LLM extraction questions over downloaded sources, writing structured outputs. Questions are defined per category in `constants.py` (`EXTRACTION_QUESTIONS`).

```bash
minerva evidence extract \
  --root hard-disk/reports/00-companies/12-robinhood \
  --profile default
```

Optional flags:
- `--source-prefix data/sources/10-K` — filter by source path prefix
- `--match "2025"` — filter by filename match
- `--force` — recompute even if outputs already exist
- `--model gemini-2.0-flash` — model override

Outputs are written to `data/meta/extraction-runs/`.

---

### `minerva evidence inventory`

Recomputes the evidence inventory from the ledger and disk state. Detects sources recorded as `downloaded` but missing on disk.

```bash
minerva evidence inventory \
  --root hard-disk/reports/00-companies/12-robinhood
```

Writes `data/meta/inventory.json` and optionally refreshes `INDEX.md` files.

---

### `minerva evidence migrate`

Migrates a V1 `source-registry.json` to the V2 `evidence.jsonl` ledger. HTML-only sources are dropped. The old registry is archived as `source-registry.archive.json`.

```bash
minerva evidence migrate \
  --root hard-disk/reports/00-companies/12-robinhood
```

Run once per company that was initialized under the V1 workflow. After migration, all V2 commands operate on the new ledger.

---

## Typical workflow

```bash
# 1. Initialize the workspace
minerva evidence init --root .../12-robinhood --ticker HOOD --name Robinhood --slug robinhood

# 2. Collect SEC filings from EDGAR
minerva evidence collect sec --root .../12-robinhood --ticker HOOD --annual 3 --quarters 4 --earnings 4

# 3. Add any external sources manually
minerva evidence add-source --root .../12-robinhood --title "Nilson Report" \
  --category industry-report --status downloaded --path .../nilson-2025.pdf

# 4. Run the evidence audit (LLM gap assessment)
minerva evidence audit --root .../12-robinhood

# 5. Check analysis readiness
minerva analysis status --root .../12-robinhood

# 6. Build analysis context (once audit passes)
minerva analysis context --root .../12-robinhood
```

---

## Migration note

If the workspace was initialized with the V1 workflow (presence of `data/meta/source-registry.json`):

```bash
minerva evidence migrate --root <company-root>
```

This reads the V1 registry, converts each non-HTML source to a V2 ledger entry, and archives the old file. Existing monolithic filing `.md` files are preserved; per-section files will be populated on the next `collect sec` run.
