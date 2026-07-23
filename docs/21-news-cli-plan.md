# Minerva news CLI implementation plan

**Date:** July 23, 2026
**Status:** Approved for implementation
**Primary command surface:** `minerva news ingest`, `minerva news exist`

---

## Objective

Promote the morning-brief news ingestion and deterministic duplicate lookup into a first-class, importable Minerva domain with one shared article-identity implementation. Replace script-specific calls and the injected recent-title/URL dump with CLI calls while preserving the current ingestion schema, output, and cleanup behavior.

## Command contract

### `minerva news ingest`

- Preserve the modes and options from `scripts/ingest_news.py`: exactly one of `--all`, `--date`, or `--raw-dir`; optional `--summaries-dir` only when paired with `--raw-dir`; optional `--news-root`, `--db`, `--news-sources`, `--ir-registry`, repeatable `--enrich`, and `--report`.
- Preserve raw-markdown parsing, same-name summary joins, source resolution, exclusions, publication normalization/fallbacks, stable SHA-256 article keys, schema creation/migration, `INSERT OR IGNORE` duplicate counting, report lines, and one-line JSON statistics.
- Keep ingestion as the only SQLite writer in the collector pipeline.

### `minerva news exist`

- Require `--db` and `--source-id`; read candidate JSON from stdin by default or from `--input` (`-` also means stdin).
- Validate a JSON array whose items contain a non-empty string `title`, a string `url` (empty allowed), and an optional string/null `published` value.
- Open an existing SQLite database with URI `mode=ro`, enable `PRAGMA query_only`, and use parameterized SQL only.
- Deduplicate later candidates within the batch before SQLite work, labeling exact URL repeats as `batch_url` and identity repeats as `batch_article_key`.
- For each first occurrence, match in deterministic order:
  1. exact non-empty URL;
  2. exact ingestion identity key when `published` normalizes to a date.
- Reuse the ingestion domain's publication normalizer, title normalizer, and article-key function.
- Return compact JSON with status, `seen` entries (`index` and `match`), and `unseen` indexes.
- Treat each first occurrence as unseen when the database or `news` table is missing, while still labeling later in-batch duplicates; never create or mutate database state. Report malformed input as a concise command error without a traceback.

## Architecture

1. Add `src/harness/news.py` as the importable domain module. Move ingestion behavior there and add candidate parsing/read-only existence classification beside the shared identity helpers.
2. Add `src/harness/commands/news.py` as a thin Typer adapter. It owns option validation, stdin/file input selection, CLI error rendering, and JSON output; domain behavior remains directly testable.
3. Register the `news` group in `src/harness/commands/__init__.py`. Keep news out of the internal `minerva run` dispatcher: collectors call the first-class Typer commands directly, so a second manual flag parser would duplicate the command surface.
4. Remove `scripts/ingest_news.py` after callers and tests use the importable domain/CLI. Do not add or retain a separate `check_news_dedup.py`; one domain and one CLI are the source of truth.

## Morning-brief integration

- Remove construction and injection of the recent title/URL dump from `scripts/run_morning_brief.sh`.
- Render an existence command based on the existing `MINERVA_RUNNER`, anchored with `cd` to the repository root so agents running from another workspace resolve the checked-out CLI, and inject that command plus `INVEST_DB` into both collector prompts.
- Give each collector a physically isolated ephemeral source root containing its own `raw/`, `candidates/`, `lookups/`, and `logs/` directories. Render `NEWS_DIR` to that root, and forbid collectors from inspecting or changing any parent, sibling, or other source files. Collectors call `news exist --input` and redirect compact results to files in their own root; no candidate JSON is embedded in shell commands.
- After all collectors exit, aggregate source `raw/*.md` files into the central run `raw/` directory in deterministic lexical order. Treat duplicate filenames as a fatal collision rather than overwriting; collector-generated and shell-generated error artifacts use this same path.
- Change ingestion to `run news ingest ...`, preserving the report, JSON stats file, duplicate count, and cleanup rule: delete the temporary run directory only after successful ingestion (or a successful no-input path).
- Use one shared collector shell helper with one `openclaw agent` invocation and no automatic retries. Launch every configured standard and IR collector before a single shared wait—there is intentionally no IR batch or replacement concurrency ceiling (the current 48 IR feeds are expected). Preserve one window/tab per browser agent.
- Configure collector timeouts with positive-integer environment variables validated before temporary state is created: `MINERVA_BROWSER_TIMEOUT` defaults to 900 seconds and `MINERVA_WEBFETCH_TIMEOUT` defaults to 300 seconds, both safely below the 30-minute no-output watchdog by default.

## Prompt behavior

### Browser collector

- Remove the 15-article cap and scan the complete landing page.
- Open exactly one browser window with exactly one tab, once. Navigate that tab forward and back; never open a second tab/window.
- Capture landing-page candidate title, destination URL, and visible date before visiting articles. Write all candidates to the per-source candidate file, batch them through `minerva news exist --input`, and visit/extract only unseen indexes.
- If a landing-page date is unavailable, rely on URL matching first. In the same tab, inspect article date metadata and rerun a one-item existence check before body extraction; if no date exists, use the run date to mirror ingestion's collection-date fallback.

### Web-fetch collector

- Replace the recent-items dump with the same file-based batched `minerva news exist` contract, including empty URLs for items without distinct destinations and the run date when neither a URL nor publication date exists.
- Remove arbitrary item-count limits while preserving relevance and date-window policies.
- For each unseen candidate with a distinct destination, fetch that item URL before writing full content. Calendar rows without distinct URLs may reuse landing-page content.

## Test plan

Focused tests will cover:

- root/group/subcommand registration and help, including the exact singular `exist` spelling;
- ingestion behavior, schema migration/idempotency, summaries, reports, duplicate counts, JSON stats, and stable exact article keys/title normalization;
- existence lookup by URL and article key, unseen candidates, empty URLs, malformed JSON, stdin/`--input`, missing database/table behavior, and deterministic in-batch URL/article-key deduplication;
- proof that existence checks are read-only/query-only and do not change database files;
- URL-index creation in new and migrated schemas, plus clear errors for malformed source registries while absent optional registries remain valid;
- shell and prompt integration: physically isolated per-source roots, behavior under a cross-source deletion attempt, deterministic collision-safe raw aggregation (including errors), direct CLI ingestion, one shared no-retry collector helper, all IR collectors launched before one shared wait with no concurrency ceiling, validated configurable timeout defaults, one-window/one-tab browser instructions, URL fetches before web-fetch writes, no arbitrary item caps, the official `gemini-3.6-flash` summarization model, and successful-cleanup semantics.

## Verification gates

Run, in order:

```bash
uv run pytest tests/test_harness/test_news.py tests/test_ingest_news.py -q
uv run pytest tests/test_harness/test_morning_brief.py -q
uv run pytest
uv run ruff check .        # only if Ruff is configured/available
bash -n scripts/run_morning_brief.sh
git diff --check
```

Also smoke-check:

```bash
uv run minerva news --help
uv run minerva news ingest --help
uv run minerva news exist --help
```

## Implementation order

1. Add this plan and index entry before code changes.
2. Move ingestion into the domain module and redirect existing tests.
3. Add candidate validation/read-only existence lookup with focused domain tests.
4. Add and register the Typer commands; keep the internal dispatcher unchanged.
5. Update collector prompts and morning-brief shell integration; remove obsolete scripts/dump logic.
6. Run focused tests, full tests, static/shell checks, and inspect the final diff without committing or pushing.
