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
