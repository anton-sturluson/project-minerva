# Original-source weekly ideas

HF Best Ideas supplies company/fund leads only. Original manager letters supply thesis evidence. The workflow is part of `minerva ideas`.

## Storage

Set `MINERVA_DATABASE_URL` to the existing shared Postgres connection. Minerva owns only schema `minerva_ideas`; it does not modify OpenClaw tables. Credentials are not printed. Set `MINERVA_IDEAS_ROOT` to the report root (default `hard-disk/reports/05-weekly-ideas`).

The initial schema has two tables: `runs` (issue identity and creation time) and `items` (roster identity and current work state). Source material and readable exports live under `<root>/<issue-date>/runs/<run-id>/research/`. Paths are derived from the configured root. There is no company master, alias registry, generic task queue, or event store.

Files are finalized before their database records are committed. Interrupted work may leave unregistered files; it cannot commit a partial roster. Existing artifact files cannot be silently replaced.

## Commands

```sh
uv run minerva ideas init
uv run minerva ideas import issue.json --run-id <uuid>
uv run minerva ideas status <uuid>
```

Input format:

```json
{"url":"https://hfbestideas.substack.com/p/example","date":"2026-09-30","roster":[{"company":"Example","fund":"Example Fund","symbol":"EX US"}]}
```

A repeated import with the same UUID and content is idempotent. A new UUID is a separate run. Duplicate company/fund roster rows are preserved by ordinal.

## PR sequence

1. Postgres and filesystem contract; roster import and status.
2. Original-document collection and scoped evidence locations.
3. Bounded source research from newsletter leads.
4. Evidence-backed extraction using a low-cost model.
5. Resumable workflow.
6. Publication preparation and delivery tracking.
7. Existing OpenClaw job integration and live acceptance.

Each PR must include tests and a live check. Deployment to the shared Postgres requires the actual connection; a disposable Postgres integration test does not establish deployment access. Never store credentials or private transcripts in Git.

## Validation

PR 1: three focused tests passed against disposable PostgreSQL 17. Imported the archived September 30 issue through the actual CLI: 50 roster rows persisted. No model calls or Slack publication. The shared database connection is still being identified.

PR 2 adds a nullable document reference to each item. `minerva ideas source RUN ORDINAL URL` archives a public manager PDF/HTML candidate with a byte hash and stable page/block IDs. It rejects HF evidence URLs and local endpoints. Source attachment is not semantic approval. Live check: fetched the Munro June 2026 manager PDF, archived all 12 pages, and persisted the document reference in disposable Postgres. Six document tests passed.

PR 3 adds `minerva ideas research RUN ORDINAL --model gemini-2.5-flash-lite`. Each lead has at most two Brave searches, six downloads (including archive navigation), and three model assessments. Manager archive links are followed to original PDFs. Aggregator results are not thesis evidence. Provider failures propagate as operational errors rather than being mislabeled as unavailable sources. Search/model traces remain files, with no new database tables.

Live checks now use the existing shared PostgreSQL instance on loopback port 55432, database `minerva`, exclusively within `minerva_ideas`. The 50-row issue was imported there. Discovery found the Munro original and recovered Greenhaven's Q2 2026 PDF for Burford without a catalog mapping. These checks supersede the earlier pending shared-connection note. Gemini 2.5 Flash-Lite was used; public-source transfers were explicitly approved. Schema compatibility and manager-archive navigation were fixed based on these live tests.

PR 4 adds one `view` JSONB field containing summary claims and passage IDs. Exact evidence and model transcripts stay on disk. The model selects IDs; Python copies the original passages, avoiding quote-transcription failures. Each view undergoes a separate semantic support review with at most one correction. Equity versus credit, stance, and explicitly stated action remain separate. Re-extraction first clears the previous approved view.

Live extraction passed on AMD and Burford using Gemini 2.5 Flash-Lite. An authentic quote paired with a fabricated guarantee was rejected. The Burford check exposed a claim whose selected quote omitted the comparison it made; replacing model-copied quotes with deterministic passage references resolved it. Semantic review reduces unsupported claims but is not a proof of factual correctness.

PR 5 adds `run` and `resume`. The live RSS parser handles HTML-encoded roster bullets and saves the selected XML content as YAML. Unchanged issues reuse their run; changed rosters start a new run. Completed views and known gaps are skipped unless `--retry-gaps` is explicit. A Postgres session advisory lock prevents concurrent work and releases on process failure. Provider/configuration failures stop the batch instead of being counted as source gaps.

Full live pass: all 50 views attempted, 12 ready and 38 gaps, zero execution failures. A targeted ten-gap retry after correcting regulatory-footer navigation and PDF line-break matching produced 14 ready / 36 gaps. The real feed-to-run command then returned the same run with `processed=0`. A concurrent invocation was rejected before additional research. Gaps mean no verified evidence within the configured budget, not that a letter does not exist.

PR 6 adds the third and final table, `publications`: payload hash, run/job IDs, route, state, preparation time, and a compact confirmed receipt. The payload itself stays on disk. `render` has no model calls; it rechecks original source identity and claim references. `prepare` records a single attempt for the configured Slack route; an uncertain attempt cannot be blindly repeated. `reconcile` requires exact content, the expected destination, and a fresh successful Gateway transport record. A confirmed duplicate returns `NO_REPLY`.

Reading the live rendered output caught false approvals that unit tests had not exposed: sibling-fund attribution, manager names substituted for companies, and performance-only views. Deterministic issuer/fund checks now reject these, and semantic review explicitly requires investment reasoning. Identity assessment also selects source block IDs rather than copying quotes. Source text remains on disk; the database stores compact references. Existing original URLs from the earlier work were rechecked as candidate inputs, not accepted without verification.

After these stricter gates and rechecking supplied originals, the current issue has 12 eligible views and 38 gaps. This supersedes the earlier 14-view count. Postgres duplicate/receipt lifecycle tests passed with isolated rows removed afterward; no Slack message was sent during those tests.
