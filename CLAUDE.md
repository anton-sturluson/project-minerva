# Minerva Project

## Tooling
- **Package manager**: `uv` is the primary package manager
- **Build backend**: hatchling
- **Python version**: 3.12
- **Project layout**: src layout (`src/minerva/`, `src/jobwatch/`)

### uv Commands
- **Install all deps**: `uv sync --extra jobwatch`
- **Run crawler**: `uv run jobwatch-crawl` (or `uv run python -m jobwatch.crawler`)
- **Run dashboard**: `uv run jobwatch-dashboard` (or `uv run python -m dashboard.app`)
- **Run tests**: `uv run pytest`
- **Add a dependency**: `uv add <pkg>` (core) or `uv add --optional jobwatch <pkg>` (jobwatch-only)

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
- **`hard-disk/`**: Main workspace for the coding agent — download files, take notes, and create one-time scripts here. Use this folder freely to save work.
- **`hard-disk/knowledge/`**: Indexed knowledge base by topic. See [Knowledge Base](#knowledge-base).
- **`src/minerva/`**: Equity research library. Reusable modules for SEC filings, valuation, formatting.
- **`src/jobwatch/`**: Job posting tracker. ATS crawlers, LLM classifier, SQLite storage. See [JobWatch](#jobwatch).
- **`dashboard/`**: FastAPI + Jinja2/HTMX web dashboard for JobWatch.
- **`data/jobwatch.db`**: SQLite database for JobWatch (gitignored).
- **`tests/test_jobwatch/`**: JobWatch test suite with ATS fixtures.
- **Research co-location**: All research source materials (downloaded filings, scraped articles, fetched transcripts) must be saved inside the report folder they support (e.g., `hard-disk/reports/{REPORT}/research/`), never in a separate top-level directory. Each report should be self-contained.

## Library Reference

### minerva.models
Pydantic data models for equity research: `CompanyProfile`, `RevenueStream`, `RiskFactor`, `IncomeStatementSnapshot`, `BalanceSheetSnapshot`, `CashFlowSnapshot`, `AnalystConsensus`, `CompetitorProfile`, `Executive`, `GrowthCatalyst`, `GeographicSegment`. Enums: `Sector`, `RiskSeverity`, `AnalystRating`.

### minerva.formatting
USD/pct formatting, markdown tables, XML conversion:
- `format_usd(value, decimals=2, auto_scale=True)` — `$1.50B`, `$95.00M`, `$1.50K`
- `format_pct(value, decimals=1)` — `12.5%`
- `format_multiple(value, suffix="x")` — `2.5x`
- `build_markdown_table(headers, rows, alignment)` — generic markdown table builder
- `calculate_growth_rate(current, prior)` — YoY growth as percentage
- `calculate_margin(numerator, denominator)` — margin as percentage
- `xml_to_yaml(xml_path, yaml_path=None)` — convert XML file to YAML format

### minerva.valuation
DCF, comps, reverse DCF, SOTP valuation engine + report generation:
- Models: `DCFAssumptions`, `CompsAssumptions`, `SOTPSegment`, `DCFResult`, `CompsResult`, `ReverseDCFResult`, `SOTPResult`
- `run_dcf(assumptions)`, `run_comps(assumptions)`, `run_reverse_dcf(...)`, `run_sotp(segments, net_cash, shares)`
- `dcf_sensitivity_matrix(assumptions, wacc_range, tgr_range)` — WACC vs TGR price matrix
- `generate_valuation_report(...)` — complete markdown valuation report

### minerva.report_generator
`generate_report(profile: CompanyProfile) -> str` — full equity research markdown from a CompanyProfile model.

### minerva.sec
SEC EDGAR helpers built on `edgartools`:
- `get_13f_comparison(cik)` — fetch latest 13-F and compare with previous quarter. Returns dict with `current`, `previous`, `comparison`, `new`, `exited`, `increased`, `decreased` DataFrames.
- `get_10k_items(ticker_or_cik, items=["1","1A","7"])` — extract specific items from most recent 10-K filing.

### minerva.text_analysis
Text analysis for financial filings:
- `KeywordGroup(name, keywords)` — dataclass for named keyword sets
- `SentimentResult` — dataclass with `confidence_count`, `uncertainty_count`, `net_score`, `paragraph_count`
- `count_keyword_group(text, keywords)` / `count_keyword_groups(text, groups)` — keyword counting
- `compute_keyword_density(text, groups, per_n_words=10_000)` — density per N words
- `split_into_chunks(text, chunk_size, overlap_ratio)` — overlapping word-level chunking
- `extract_topic_paragraphs(text, triggers, chunk_size)` — extract chunks mentioning triggers
- `score_sentiment(paragraphs, confidence_words, uncertainty_words)` — confidence vs uncertainty
- `classify_risk_themes(text, themes, triggers)` — count paragraphs by theme
- `normalize_0_1(values)` — min-max normalization
- Default word sets: `DEFAULT_CONFIDENCE_WORDS`, `DEFAULT_UNCERTAINTY_WORDS`, `DEFAULT_FINANCIAL_STOPWORDS`

### minerva.plotting
Matplotlib chart utilities:
- `THEME_LIGHT` / `THEME_DARK` — rcParams theme dicts
- `apply_theme(theme=None)` — apply theme (defaults to THEME_LIGHT)
- `save_fig(fig, path, dpi=150, close=True)` — save and optionally close figure
- `axis_formatter_millions(x, pos)` — `"$95M"` tick formatter
- `axis_formatter_billions(x, pos)` — `"$1.5B"` tick formatter
- `axis_formatter_pct(x, pos)` — `"50%"` tick formatter

## JobWatch

Job posting tracker for AI startups. Crawls ATS APIs, classifies with LLM, stores in SQLite.

**Target companies (v1):** Anthropic, xAI (Greenhouse); OpenAI (Ashby SSR); Cursor, Cognition (Ashby)

### jobwatch.models
Enums: `Department`, `RoleType`, `Seniority`, `ATSType`, `CrawlStatus`, `ReclassifyTrigger`, `WorkMode`, `EmploymentType`.
Models: `RawPosting`, `FetchResult`, `JobClassification`.
Constants: `TAXONOMY_VERSION`, `PROMPT_VERSION`.

### jobwatch.config
- `CompanyConfig` — frozen dataclass (id, name, ats_type, ats_board, website)
- `COMPANY_REGISTRY` — list of 5 target companies
- `Settings` — runtime settings (db_path, classifier_model, taxonomy/prompt versions)
- `get_company(company_id)` — lookup by id

### jobwatch.ats
- `ATSClient` (ABC) — `fetch_all() -> FetchResult`
- `GreenhouseClient` — Anthropic, xAI (boards-api.greenhouse.io)
- `AshbyClient` — Cursor, Cognition (api.ashbyhq.com)
- `AshbySSRClient` — OpenAI (SSR scrape of `window.__appData`, brittle)

### jobwatch.db
`JobWatchDB(db_path)` — SQLite wrapper. Key methods:
- `init_db()`, `ensure_company()`, `create_crawl_run()`, `update_crawl_run()`
- `upsert_posting()`, `close_posting()`, `insert_classification()`, `has_current_classification()`
- `insert_snapshot()`, `get_snapshots()`, `get_department_mix()`, `get_role_type_counts()`
- `get_low_confidence()`, `get_recent_crawl_runs()`, `get_all_active_postings_with_classifications()`

### jobwatch.classifier
- `ClassifierProvider` (ABC) — `classify(title, department_raw, description) -> JobClassification`
- `AnthropicClassifier` — Claude Haiku (default `claude-haiku-4-5-20251001`)
- `OpenAIClassifier` — GPT-4o-mini (default)
- `classify_postings(provider, postings)` — batch sequential classification

### jobwatch.crawler
- `crawl_company(db, company, classifier, settings)` — full per-company pipeline
- `crawl_all(db, classifier, settings, company_ids)` — serial crawl over registry
- `main()` — CLI entry point (argparse: `--companies`, `--db-path`, `--classifier`, `--model`)

### dashboard.app
FastAPI + Jinja2/HTMX. Routes: `/`, `/company/{id}`, `/compare`, `/trends`, `/heatmap`, `/health`.
HTMX partials: `/api/dept-mix/{id}`, `/api/trend-data/{id}`. 90s retro light-mode aesthetic.

### edgartools usage patterns
`edgartools` is installed and provides comprehensive SEC EDGAR access. Use it directly for simple operations:
```python
from edgar import Company, set_identity
set_identity("Minerva Research minerva@research.dev")
c = Company("AAPL")
c.income_statement(periods=5, period='annual', as_dataframe=True)  # financials
c.balance_sheet(periods=5, period='annual', as_dataframe=True)
c.cashflow_statement(periods=5, period='annual', as_dataframe=True)
c.get_filings(form=[3, 4, 5])  # insider transactions
c.get_filings(form="10-K").latest(1)  # latest 10-K
```
Full XBRL support via `Company.income_statement()`, `XBRL`/`XBRLS` classes. No custom XBRL module needed.

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
