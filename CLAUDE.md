# Minerva Project

## Tooling
- **Package manager**: `uv`
- **Build backend**: hatchling
- **Python version**: 3.12
- **Project layout**: src layout (`src/minerva/`, `src/harness/`, `src/jobwatch/`)
- **Install deps**: `uv sync --extra jobwatch`
- **Run tests**: `uv run pytest`

## CLI entry points
Declared in `pyproject.toml`:
- `minerva` → `harness.cli:app` — primary investment harness CLI (SEC filings, evidence, valuation, morning brief). Run `uv run minerva --help` to discover subcommands.
- `jobwatch-crawl` → `jobwatch.crawler:main` — ATS crawler.
- `jobwatch-dashboard` → `dashboard.app:main` — JobWatch web UI.

## Data Handling
- **Always convert downloaded XML files to YAML format** for readability and downstream use.

## Citation Standard

Every piece of information in a report must be traceable to a reliable source and easily verifiable by the reader.

- **Inline citations**: Where a claim is made, cite the source inline as a clickable markdown hyperlink — e.g., `([TOST 10-K FY2024](url))`. When no URL is available, use a plain-text parenthetical with enough detail to locate the source (e.g., filing name, date, page).
- **References section**: Every report ends with a `## References` section listing all cited sources as clickable hyperlinks, grouped by category (SEC Filings, Earnings & Transcripts, Industry Research, etc.). Each entry includes a brief note on what data was sourced.
- **Unverified data**: Flag any figure that comes from a single non-authoritative source or cannot be independently verified.

## Knowledge Base

`hard-disk/knowledge/` is the project's persistent, curated knowledge store.

### Folder structure

All folders — topics and subtopics alike — use a two-digit index prefix for stable ordering:

```
hard-disk/knowledge/
├── 00-saas/
│   ├── metrics-benchmarks.md
│   └── 00-unit-economics/
│       └── cac-payback.md
├── 01-healthcare/
└── ...
```

- **Naming**: `{NN}-{slug}/` — lowercase, hyphenated. Index gaps are fine for future inserts.
- **Knowledge files**: Markdown (`.md`) inside any folder. One file per focused subject.

### Topic index

Living index of established topics. Update this list when creating new topic folders.

- `00-saas/` — SaaS metrics, valuation multiples, operating benchmarks, unit economics
- `01-platform-economics/` — Platform value capture, front-door dynamics
- `02-travel-tech/` — OTAs, GDS platforms, travel industry value migration

### Knowledge file format

Each file must include:

1. **YAML frontmatter** — `title`, `created`, `updated`, optional `tags`
2. **Body** — concise, factual content with inline citations per the Citation Standard
3. **References section** — same format as reports

### Usage rules

- **Consult before research**: Agents MUST check `hard-disk/knowledge/` before starting new research or reports.
- **Contribute after research**: Distill reusable insights and benchmarks into knowledge files after completing reports.
- **No duplication**: Capture reusable facts and frameworks — not report-specific analysis.
- **Keep current**: Update the `updated` frontmatter field when revising. Remove or flag outdated information.
- **Update topic index**: When creating a new topic folder, add it to the topic index above.

## Directory Structure
- **`src/harness/`** — Investment harness CLI and workflows (morning brief, evidence, portfolio state). Primary active package.
- **`src/minerva/`** — Equity research library: models, valuation, SEC helpers, formatting, text analysis, plotting.
- **`src/jobwatch/`** — ATS crawler and LLM classifier for AI-startup job postings.
- **`dashboard/`** — FastAPI + Jinja2/HTMX web dashboard for JobWatch.
- **`tests/`** — Test suite.
- **`scripts/`** — One-off and scheduled shell entry points (e.g., `run_morning_brief_v1.sh`).
- **`docs/`** — Design docs and architecture notes. See `docs/INDEX.md`.
- **`profiles/`** — Company/portfolio profile inputs.
- **`data/`** — Runtime data (gitignored, e.g., `data/jobwatch.db`).
- **`hard-disk/`** — Agent workspace for downloads, notes, and one-off scripts. See [Knowledge Base](#knowledge-base) for `hard-disk/knowledge/`.
- **`worktrees/`** — Git worktrees live here (see below).
- **Research co-location**: All research source materials (downloaded filings, scraped articles, fetched transcripts) must be saved inside the report folder they support (e.g., `hard-disk/reports/{REPORT}/research/`), never in a separate top-level directory. Each report should be self-contained.

## Git Worktrees

All git worktrees must be created inside the top-level `worktrees/` folder, one subdirectory per worktree (e.g., `worktrees/backtesting/`). Do not create worktrees elsewhere in the repo or outside it. The `worktrees/` directory itself is not checked in.

## Agent Memory

All agents with `memory: project` have a persistent memory directory at `.claude/agent-memory/{agent-name}/`. Contents persist across conversations.

Guidelines:
- `MEMORY.md` is loaded into the agent's system prompt (keep under 200 lines)
- Create separate topic files (e.g., `patterns.md`) for detailed notes; link from MEMORY.md
- Update or remove memories that turn out to be wrong or outdated
- Organize semantically by topic, not chronologically

**Save**: Stable patterns, key decisions, important file paths, user preferences, recurring solutions.
**Don't save**: Session-specific context, unverified info, anything duplicating CLAUDE.md.

When the user asks to remember/forget something, update memory files immediately.

### Searching past context

1. Search agent memory: `Grep pattern="<term>" path=".claude/agent-memory/{agent-name}/" glob="*.md"`
2. Session logs (last resort): `Grep pattern="<term>" path in project .claude dir glob="*.jsonl"`
