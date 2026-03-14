# JobWatch — Architecture & Data Model

## Overview

JobWatch crawls public job postings from AI startups via ATS APIs, classifies them with an LLM, stores results in SQLite, and serves a retro-themed dashboard for tracking hiring trends over time.

**Target companies (v1):** OpenAI, Anthropic, xAI, Cursor, Cognition

---

## 1. Non-Goals / v1 Scope

**In scope:**
- 5 target companies via known ATS APIs
- Weekly manual crawl (CLI command)
- LLM classification into department / role type / seniority
- SQLite storage with time-series snapshots
- Local-only dashboard with retro aesthetic
- Single user (no auth, no multi-tenancy)

**Out of scope for v1:**
- Arbitrary company onboarding / generic scraper framework
- Real-time or continuous crawling
- Compensation analysis or salary benchmarking
- Applicant tracking or application submission
- Headless browser scraping (Playwright/Selenium)
- Multi-user access, hosted deployment, or scheduled cron
- Recruiting intelligence features (candidate matching, sourcing, etc.)

---

## 2. System Architecture

```
┌──────────────┐     ┌─────────────────┐     ┌──────────────┐     ┌──────────────┐
│  ATS Router  │────▶│  LLM Classifier │────▶│   SQLite DB  │────▶│  Dashboard   │
│ (Greenhouse, │     │  (Haiku / GPT-  │     │              │     │ (FastAPI +   │
│  Ashby)      │     │   5-mini)       │     │              │     │  HTMX, 90s)  │
└──────────────┘     └─────────────────┘     └──────────────┘     └──────────────┘
       ▲                                            ▲                     │
       │                                            │                     │
   Weekly crawl                              Single-writer           Browser
   (manual CLI)                              path (serialized)
```

### Components

| Component | Responsibility |
|-----------|---------------|
| **ATS Router** | Route to correct API client based on company's `ats_type` |
| **ATS Clients** | Greenhouse, Ashby API adapters + abstract base for custom scrapers — return normalized `RawPosting` |
| **LLM Classifier** | Classify postings into department + role_type + seniority via structured output |
| **Storage** | SQLite with crawl provenance, versioned classifications, time-series snapshots |
| **API Layer** | Thin FastAPI service over SQLite — dashboard reads stable endpoints, not raw DB |
| **Dashboard** | FastAPI + Jinja2/HTMX web UI for hiring trends, category breakdowns, velocity |

---

## 3. ATS API Details (Verified)

| Company | ATS | Board Slug | API Endpoint | Notes |
|---------|-----|-----------|-------------|-------|
| **Anthropic** | Greenhouse | `anthropic` | `GET boards-api.greenhouse.io/v1/boards/anthropic/jobs?content=true` | ~200 postings. Public, no auth. |
| **xAI** | Greenhouse | `xai` | `GET boards-api.greenhouse.io/v1/boards/xai/jobs?content=true&per_page=500` | ~194 postings. Public, no auth. |
| **OpenAI** | Ashby (SSR) | `openai` | SSR scrape of `jobs.ashbyhq.com/openai` (`window.__appData` JSON blob) | REST API returns ~9 jobs (subset). SSR scrape required for full list. Brittle integration — requires fixtures and regression tests. |
| **Cursor** | Ashby | `cursor` | `GET api.ashbyhq.com/posting-api/job-board/cursor` | ~20 postings. Public, no auth. |
| **Cognition** | Ashby | `cognition` | `GET api.ashbyhq.com/posting-api/job-board/cognition` | ~48 postings. Public, no auth. Ashby client must handle pagination exhaustively. |

### Client Hierarchy

```
ATSClient (abstract base)
├── GreenhouseClient    — Anthropic, xAI
├── AshbyClient         — Cursor, Cognition (handles pagination generically)
└── AshbySSRClient      — OpenAI (scrapes __appData from SSR HTML)
```

All clients return normalized `RawPosting` objects so downstream code is ATS-agnostic. The abstract base class ensures new custom scrapers follow the same interface.

Each client must:
- Traverse all pages / results exhaustively before returning
- Report a `is_complete: bool` flag indicating whether the full job list was retrieved
- Return a content hash of the raw response for change detection

---

## 4. Job Taxonomy

### Department (L1)

| Code | Department |
|------|-----------|
| `ENG` | Engineering |
| `RES` | Research |
| `PROD` | Product |
| `DES` | Design |
| `DATA` | Data & Analytics |
| `INFRA` | Infrastructure & IT |
| `SEC` | Security |
| `SALES` | Sales & Business Development |
| `MKT` | Marketing & Communications |
| `CS` | Customer Success & Support |
| `OPS` | Operations |
| `PPL` | People & Talent |
| `FIN` | Finance & Accounting |
| `LEGAL` | Legal & Policy |
| `EXEC` | Executive & Leadership |
| `UNKNOWN` | Unclassifiable / needs human review |

### Role Type (L2) — Engineering only

L2 subcategories are defined only for Engineering. All other departments use `{DEPT}.GEN` as the default role type. We crawl and store all postings regardless — the taxonomy can be expanded later as data volume justifies it.

**ENG — Engineering**
| Code | Role Type |
|------|-----------|
| `ENG.FE` | Frontend |
| `ENG.BE` | Backend |
| `ENG.FS` | Full-Stack |
| `ENG.ML` | ML Engineering |
| `ENG.PLAT` | Platform / Infrastructure |
| `ENG.SRE` | SRE / DevOps |
| `ENG.MOB` | Mobile |
| `ENG.DATA` | Data Engineering |
| `ENG.SEC` | Security Engineering |
| `ENG.EMBEDDED` | Embedded / Systems |
| `ENG.QA` | QA / Test |
| `ENG.FDE` | Forward-Deployed Engineer |
| `ENG.GEN` | General / unspecified engineering |

**All other departments** → `{DEPT}.GEN` (e.g., `RES.GEN`, `PROD.GEN`, `SALES.GEN`)

### Seniority

| Code | Level |
|------|-------|
| `INTERN` | Intern |
| `JUNIOR` | Junior / Entry-level |
| `MID` | Mid-level |
| `SENIOR` | Senior |
| `STAFF` | Staff / Principal |
| `LEAD` | Lead / Manager |
| `DIRECTOR` | Director |
| `VP` | VP |
| `C_LEVEL` | C-Suite |
| `UNKNOWN` | Cannot determine from posting |

### Precedence Rules for Ambiguous Roles

Common AI-company titles that span categories:

| Title Pattern | Classification | Rationale |
|---------------|---------------|-----------|
| Research Engineer | `ENG.ML` | Engineering role that supports research — classify by function |
| Applied AI Engineer | `ENG.ML` | Applied = engineering, not research |
| Member of Technical Staff (MTS) | `ENG.GEN` | Generic engineering unless description clarifies |
| Research Scientist | `RES.GEN` | Research role regardless of engineering overlap |
| Technical Program Manager | `PROD.GEN` | Program management lives in Product |
| Solutions Architect | `SALES.GEN` | Customer-facing technical role |
| ML Infrastructure Engineer | `ENG.PLAT` | Infra function, ML domain |
| Developer Experience Engineer | `ENG.PLAT` | Platform / tooling function |

**When in doubt:** If confidence < 0.6, classify as `UNKNOWN` department or `{DEPT}.GEN` role type. These get flagged for review. The classifier should never force a low-confidence classification into a specific bucket.

---

## 5. Data Model

### Classification Pydantic Model

The LLM returns structured output matching this schema. `justification` is an optional short note for debugging misclassifications — not a reasoning crutch. The real contract is deterministic structured output.

```python
class JobClassification(BaseModel):
    justification: str      # Optional short note (1-2 sentences) for audit/debugging
    department: str         # L1 code: "ENG", "RES", etc.
    role_type: str          # L2 code: "ENG.ML", "RES.GEN", etc.
    seniority: str          # "SENIOR", "STAFF", etc.
    confidence: float       # self-reported confidence 0-1
```

### SQLite Tables

```sql
-- Company registry
CREATE TABLE companies (
    id          TEXT PRIMARY KEY,       -- slug: "anthropic", "openai"
    name        TEXT NOT NULL,
    ats_type    TEXT NOT NULL,          -- "greenhouse", "ashby", "ashby_ssr", "custom"
    ats_board   TEXT NOT NULL,          -- board token / company slug for ATS API
    website     TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Crawl provenance: one row per company per crawl run
CREATE TABLE crawl_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id      TEXT NOT NULL REFERENCES companies(id),
    started_at      TEXT NOT NULL,          -- ISO datetime
    finished_at     TEXT,                   -- ISO datetime (NULL if still running or failed)
    status          TEXT NOT NULL DEFAULT 'running',  -- "running", "complete", "partial", "failed"
    is_exhaustive   INTEGER NOT NULL DEFAULT 0,       -- 1 = ATS client confirmed full retrieval
    postings_found  INTEGER,                -- total postings returned by ATS
    postings_new    INTEGER,                -- new postings inserted
    postings_closed INTEGER,                -- postings marked inactive
    postings_changed INTEGER,               -- existing postings with material content changes
    response_hash   TEXT,                   -- hash of raw ATS response for change detection
    error_message   TEXT,                   -- error details if status = "failed" or "partial"
    UNIQUE(company_id, started_at)
);

-- Raw job postings
CREATE TABLE postings (
    id              TEXT PRIMARY KEY,       -- "{company_id}:{ats_job_id}"
    company_id      TEXT NOT NULL REFERENCES companies(id),
    ats_job_id      TEXT NOT NULL,          -- ID from ATS API
    title           TEXT NOT NULL,
    department_raw  TEXT,                   -- department string from ATS (before LLM classification)
    location        TEXT,
    work_mode       TEXT,                   -- "remote", "hybrid", "onsite" (normalized from ATS)
    employment_type TEXT,                   -- "full_time", "part_time", "contract", "intern"
    description     TEXT,                   -- full job description text
    content_hash    TEXT,                   -- hash of title+description for change detection
    url             TEXT,
    first_seen      TEXT NOT NULL,          -- ISO date of first crawl
    last_seen       TEXT NOT NULL,          -- ISO date of most recent crawl
    is_active       INTEGER NOT NULL DEFAULT 1,
    closed_at       TEXT,                   -- ISO date when posting was marked inactive
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(company_id, ats_job_id)
);

-- Versioned LLM classifications (history, not one-per-posting)
CREATE TABLE classifications (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    posting_id          TEXT NOT NULL REFERENCES postings(id),
    justification       TEXT NOT NULL,          -- 1-2 sentence LLM reasoning
    department          TEXT NOT NULL,          -- L1 code: "ENG", "RES", etc.
    role_type           TEXT NOT NULL,          -- L2 code: "ENG.ML", "RES.GEN"
    seniority           TEXT NOT NULL,          -- "SENIOR", "STAFF", etc.
    confidence          REAL,                   -- LLM self-reported confidence 0-1
    model               TEXT NOT NULL,          -- model used: "haiku", "gpt-5-mini"
    taxonomy_version    TEXT NOT NULL,          -- e.g., "v1" — bumped when taxonomy changes
    prompt_version      TEXT NOT NULL,          -- e.g., "v1" — bumped when classification prompt changes
    is_current          INTEGER NOT NULL DEFAULT 1,  -- 1 = active classification for this posting
    classified_at       TEXT NOT NULL DEFAULT (datetime('now')),
    triggered_by        TEXT NOT NULL DEFAULT 'new_posting'
        -- "new_posting", "content_change", "taxonomy_update", "manual_reclassify"
);

-- Index for fast "current classification" lookups
CREATE INDEX idx_classifications_current
    ON classifications(posting_id, is_current) WHERE is_current = 1;

-- Weekly snapshot for time-series (materialized at crawl time)
-- Disposable derived data — can be recomputed from postings + classifications
CREATE TABLE snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id      TEXT NOT NULL REFERENCES companies(id),
    crawl_run_id    INTEGER NOT NULL REFERENCES crawl_runs(id),
    crawl_date      TEXT NOT NULL,          -- ISO date
    total_active    INTEGER NOT NULL,
    dept_counts     TEXT NOT NULL,          -- JSON: {"ENG": 45, "RES": 12, ...}
    role_type_counts TEXT NOT NULL,         -- JSON: {"ENG.ML": 10, ...}
    seniority_counts TEXT NOT NULL,         -- JSON: {"SENIOR": 20, ...}
    new_postings    INTEGER NOT NULL,       -- new since last crawl
    closed_postings INTEGER NOT NULL,       -- disappeared since last crawl
    UNIQUE(company_id, crawl_date)
);
```

### Reclassification Triggers

A posting gets reclassified (new `classifications` row, previous row's `is_current` set to 0) when:

1. **Content change** — `content_hash` differs from stored value (title or description edited)
2. **Taxonomy update** — `taxonomy_version` bumps (new departments or role types added)
3. **Prompt update** — `prompt_version` bumps (classification prompt improved)
4. **Manual reclassify** — CLI command to reclassify specific postings or low-confidence ones

The `triggered_by` column records which of these caused the reclassification.

### Posting Change Detection

On each crawl, for existing postings:
- Compute `content_hash = sha256(title + description)` from the ATS response
- If hash differs from stored value → update posting fields, set new `content_hash`, trigger reclassification
- If hash matches → only update `last_seen`

Changes that do **not** trigger reclassification: location edits, URL changes (update the posting row but skip LLM).

### Key Queries

```sql
-- Hiring velocity: new postings per week
SELECT crawl_date, new_postings, closed_postings
FROM snapshots WHERE company_id = ? ORDER BY crawl_date;

-- Department mix for a company (current classifications only)
SELECT c.department, COUNT(*) as count
FROM classifications c JOIN postings p ON c.posting_id = p.id
WHERE p.company_id = ? AND p.is_active = 1 AND c.is_current = 1
GROUP BY c.department ORDER BY count DESC;

-- Cross-company comparison: active ML engineering roles
SELECT p.company_id, COUNT(*) as ml_roles
FROM classifications c JOIN postings p ON c.posting_id = p.id
WHERE c.role_type = 'ENG.ML' AND p.is_active = 1 AND c.is_current = 1
GROUP BY p.company_id;

-- Low-confidence classifications needing review
SELECT p.title, p.company_id, c.department, c.role_type, c.confidence, c.justification
FROM classifications c JOIN postings p ON c.posting_id = p.id
WHERE c.is_current = 1 AND c.confidence < 0.6
ORDER BY c.confidence ASC;

-- Crawl health: recent runs and their status
SELECT cr.company_id, cr.started_at, cr.status, cr.is_exhaustive,
       cr.postings_found, cr.postings_new, cr.postings_closed, cr.error_message
FROM crawl_runs cr ORDER BY cr.started_at DESC LIMIT 20;
```

---

## 6. Concurrency and Failure Model

### v1 Execution (Serial)

v1 runs serially for simplicity, but the design does not preclude concurrency.

```
for company in registry:
    run = create_crawl_run(company, status="running")
    try:
        raw_postings, is_exhaustive = ats_client.fetch_all(company)
        run.is_exhaustive = is_exhaustive
        new, changed, missing = diff(raw_postings, db_postings)
        classify(new + changed)          # LLM calls
        persist(new, changed, missing)   # single-writer DB path
        if is_exhaustive:
            close_missing(missing)       # only if exhaustive
            materialize_snapshot(run)    # only if exhaustive
            run.status = "complete"
        else:
            run.status = "partial"       # non-exhaustive: no closures, no snapshots
    except Exception:
        run.status = "failed"
        run.error_message = traceback.format_exc()
```

### Future Concurrency Model

When performance requires it:

| Phase | Concurrency | Notes |
|-------|------------|-------|
| **Fetch** | Concurrent per company, bounded per ATS provider | e.g., max 3 concurrent Greenhouse requests |
| **Parse** | Concurrent (read-only) | No shared state |
| **Diff** | Per-company, independent | No cross-company dependencies |
| **Classify** | Bounded worker pool with rate limiting | e.g., 10 concurrent LLM calls, with retry + backoff |
| **Persist** | Single-writer path | Serialized company-level transactions to avoid `database is locked` |
| **Close** | Only after crawl_run marked `complete` + `is_exhaustive` | Never mutate closure state on partial runs |
| **Snapshot** | Only after complete + exhaustive crawl | Incomplete runs do not produce official snapshots |

### Closure Safety

A posting is marked `is_active = 0` **only when all of these are true**:
1. The crawl run completed without error (`status = "complete"`)
2. The ATS client confirmed exhaustive retrieval (`is_exhaustive = 1`)
3. The posting was present in a previous crawl but absent in the current one

Incomplete, failed, or partial crawl runs **never** close postings or produce snapshots. This prevents false closures from API pagination issues, rate limiting, or parser breakage.

### Idempotency

- Classification uses `(posting_id, content_hash, taxonomy_version, prompt_version)` as a logical idempotency key. If all four match an existing `is_current = 1` row, skip classification.
- Crawl runs that die after classification but before persistence can be resumed by re-running — the diff step will detect already-classified postings and skip them.

---

## 7. Project Structure

Lives inside the monorepo under `src/jobwatch/` — a separate package alongside `src/minerva/`.

```
src/jobwatch/
├── __init__.py
├── ats/                    # ATS API clients
│   ├── __init__.py
│   ├── base.py             # ATSClient abstract base class + RawPosting model
│   ├── greenhouse.py       # Anthropic, xAI
│   ├── ashby.py            # Cursor, Cognition (handles pagination generically)
│   └── ashby_ssr.py        # OpenAI (SSR scrape of __appData — brittle, tested with fixtures)
├── classifier.py           # LLM classification (taxonomy + prompts + provider abstraction)
├── db.py                   # SQLite schema, migrations, queries
├── crawler.py              # Orchestrator: crawl → classify → store
├── models.py               # Pydantic models (shared across modules)
└── config.py               # Company registry, settings
```

Additional top-level dirs:
```
dashboard/                  # FastAPI + Jinja2/HTMX web dashboard
data/
└── jobwatch.db             # SQLite database (gitignored)
tests/
└── test_jobwatch/
    ├── fixtures/           # Frozen ATS responses (JSON/HTML) for regression tests
    ├── test_greenhouse.py  # Parser tests against Greenhouse fixtures
    ├── test_ashby.py       # Parser tests against Ashby API fixtures
    ├── test_ashby_ssr.py   # Parser tests against OpenAI SSR HTML fixtures
    ├── test_classifier.py  # Classification eval set (labeled examples)
    └── test_crawler.py     # End-to-end crawl tests against frozen payloads
```

### Packaging

`pyproject.toml` must be updated to include `src/jobwatch` in the hatch build targets:

```toml
[tool.hatch.build.targets.wheel]
packages = ["src/minerva", "src/jobwatch"]
```

JobWatch-specific dependencies (e.g., `httpx`, `openai`, `anthropic`, `fastapi`, `jinja2`) should be added to an optional dependency group:

```toml
[project.optional-dependencies]
jobwatch = ["httpx", "anthropic", "openai", "fastapi", "jinja2", "uvicorn"]
```

---

## 8. Dashboard — Aesthetic & Framework

### 90s Vibe — Light Mode
- Pixel fonts (e.g., "Press Start 2P", "VT323"), system fonts as fallback
- Saturated colors on light/off-white backgrounds — no dark mode
- Visible borders, beveled/raised UI elements (Windows 95 / classic Mac feel)
- Tiled or patterned backgrounds, chunky buttons
- Not too flashy — functional retro, not ironic GeoCities

### Framework: FastAPI + Jinja2 / HTMX

The project is Python-only, local-only, and single-user. A separate JS frontend framework is not justified for v1. FastAPI + Jinja2 templates with HTMX for interactivity keeps the stack unified and the retro aesthetic easy to achieve with plain CSS.

If the dashboard outgrows this setup, the FastAPI endpoints remain usable as a standalone API for any future frontend.

### Key Dashboard Views
1. **Overview** — total open roles per company, sparkline trends
2. **Company deep-dive** — department breakdown (bar), seniority distribution
3. **Cross-company comparison** — side-by-side department mix, hiring velocity
4. **Trend lines** — headcount over time by department or company
5. **New & closed** — recent additions/removals, churn rate
6. **Heatmap** — company x department matrix of open roles

---

## 9. Crawl Pipeline

```
1. For each company in registry:
   a. Create crawl_run record (status = "running")
   b. Call ATS client → list of RawPosting + is_exhaustive flag
   c. Diff against DB (using content_hash for change detection):
      - New postings → INSERT + classify with LLM
      - Changed postings (content_hash differs) → UPDATE fields + reclassify
      - Unchanged postings → UPDATE last_seen only
      - Missing postings (only if is_exhaustive) → SET is_active = 0, closed_at = today
   d. Materialize snapshot row (only if is_exhaustive)
   e. Update crawl_run (status, counts, response_hash)
2. Log summary: N new, N changed, N closed, N total active, crawl status
```

Crawl is triggered manually (CLI command). Cron scheduling is optional and not required for v1 — no persistent hardware yet.

### LLM Classification Prompt (sketch)

```
Classify this job posting into department, role type, and seniority.
Optionally note key evidence in the justification field (1-2 sentences max).

Title: {title}
Department (from ATS): {department_raw}
Description (first 1500 chars): {description[:1500]}

Return JSON: { justification: str, department: str, role_type: str, seniority: str, confidence: float }

Codes:
- department: ENG, RES, PROD, DES, DATA, INFRA, SEC, SALES, MKT, CS, OPS, PPL, FIN, LEGAL, EXEC, UNKNOWN
- role_type: ENG has subcategories (ENG.FE, ENG.BE, ENG.FS, ENG.ML, ENG.PLAT, ENG.SRE, ENG.MOB,
  ENG.DATA, ENG.SEC, ENG.EMBEDDED, ENG.QA, ENG.FDE, ENG.GEN). All other departments use {DEPT}.GEN.
- seniority: INTERN, JUNIOR, MID, SENIOR, STAFF, LEAD, DIRECTOR, VP, C_LEVEL, UNKNOWN

Precedence rules:
- "Research Engineer" → ENG.ML (engineering function)
- "Applied AI Engineer" → ENG.ML
- "Member of Technical Staff" → ENG.GEN (unless description clarifies)
- "Research Scientist" → RES.GEN
- "Technical Program Manager" → PROD.GEN
- "Solutions Architect" → SALES.GEN
- If confidence < 0.6, use UNKNOWN for department or {DEPT}.GEN for role type.
```

### LLM Provider Abstraction

The classifier uses a provider-agnostic interface. v1 ships with Haiku and GPT-5-mini adapters. The correct provider is chosen by building a labeled eval set and comparing accuracy + schema adherence, not by theoretical price alone. Weekly volume is small enough that cost is not the primary constraint.

---

## 10. Testing Strategy

| Test Type | What | Where |
|-----------|------|-------|
| **Parser fixtures** | Frozen JSON responses for each ATS (Greenhouse, Ashby API) | `tests/test_jobwatch/fixtures/*.json` |
| **SSR regression** | Saved HTML snapshots of `jobs.ashbyhq.com/openai` with known job counts | `tests/test_jobwatch/fixtures/openai_ssr_*.html` |
| **Parser unit tests** | Each ATS client parses its fixtures into correct `RawPosting` objects | `tests/test_jobwatch/test_greenhouse.py`, etc. |
| **Classification eval** | Labeled set of ~50 real postings with expected dept/role/seniority | `tests/test_jobwatch/test_classifier.py` |
| **End-to-end crawl** | Full pipeline against frozen payloads (no network, no LLM) | `tests/test_jobwatch/test_crawler.py` |
| **Content hash** | Verify change detection triggers reclassification correctly | `tests/test_jobwatch/test_crawler.py` |
| **Closure safety** | Verify incomplete crawls never close postings | `tests/test_jobwatch/test_crawler.py` |

Parser fixtures should be refreshed periodically to catch ATS schema changes. The OpenAI SSR fixture is the most brittle and should be checked first when tests fail.

---

## 11. Open Questions

1. ~~Dashboard framework~~ → FastAPI + Jinja2/HTMX for v1.
2. ~~API layer~~ → Thin FastAPI service layer; dashboard reads endpoints, not raw DB.
3. **LLM provider** — Haiku vs GPT-5-mini? Build eval set and compare before committing. Architecture supports swapping providers.
4. **Hosting** — Local-only for v1. When persistent hardware is available, revisit scheduler, storage backend, and deployment topology together.
