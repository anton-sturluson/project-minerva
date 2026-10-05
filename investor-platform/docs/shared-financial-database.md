# Shared financial database

This increment prepares a PostgreSQL copy of SQLite financial inputs and exposes read-only JSON queries. It does not switch live OpenClaw, change its settings/jobs or introduce a collection/write API. SQLite remains live until a separate reconciled cutover. ([Importer](../backend/src/investor_platform/financial_import.py), [CLI](../backend/src/investor_platform/financial_cli.py))

## Data contract

The `investor_data` namespace contains `companies`, `metrics`, `company_periods`, `sources`, `metric_values` and the joined `metric_values_flat` view. Company, metric, period and observation IDs are preserved. Sources use company-scoped document references; period identity uses company, kind, start and end dates. Ticker/exchange and fiscal labels are metadata rather than unique identities. Portfolio records stay in their existing schema. ([Schema](../backend/src/investor_platform/financial_schema.sql))

Exact decimals, missing statuses, ranges, scenarios, source references and legacy metadata are preserved. Imported facts remain `legacy_unverified`. SQLite REAL conversion cannot recover precision already lost. Publication dates, content hashes, source locators and metric units/scope are not inferred. Fields for reviewed units, reporting scope and duration/instant basis are available for the later publication feature; they do not make imported data calculation-ready.

## Prepare and read

From the independent backend project, run `uv sync --frozen`. Set `INVESTOR_DATA_DATABASE_URL` in a private environment or secret manager. The CLI requires it explicitly and never falls back to portfolio credentials. Do not put secrets in commands or checked-in files.

```sh
uv run investor-data inspect-sqlite --sqlite /private/path/invest.db
uv run investor-data migrate-sqlite --sqlite /private/path/invest.db
uv run investor-data verify-sqlite --sqlite /private/path/invest.db
uv run investor-data companies --ticker DEMO
uv run investor-data history --company-id 42 --metric-key revenue.total.reported
```

The importer opens SQLite read-only and takes a consistent backup including committed WAL records. Only the four financial core tables are imported; source records are derived from their references. News, prices and other tables stay in SQLite. Initialization and import share one PostgreSQL transaction. Every mapped field is compared after import; receipts contain counts and a digest rather than private records. Exact reruns are harmless; differing populated targets, unknown source columns and unsupported namespace versions are refused. ([Importer](../backend/src/investor_platform/financial_import.py))

Use `--schema investor_data_test_example` before a command for an isolated test namespace. Reads use read-only transactions and serialize decimals as strings. History defaults to actuals; `--scenario` selects guidance or estimates and `--limit` bounds the latest records returned in chronological order. Ticker searches can return several issuers. ([Read helpers](../backend/src/investor_platform/financial_store.py))

A database owner can create a fresh dedicated non-administrator `investor_data_reader` role and call `grant_reader` to give it financial SELECT access only. The helper does not revoke unrelated existing grants, so do not reuse broadly privileged roles. No writer grant or agent append command is included. ([Access helper](../backend/src/investor_platform/financial_store.py))

## Cutover boundary

The prepared copy can become stale while SQLite continues to receive writes. Reconcile changes before cutover; do not enable competing production writers. Preserve SQLite and the existing workflow throughout preparation. The namespace retains its reviewed version marker; prototype v1 and unknown versions require explicit operator handling rather than automatic changes.

Collection, verified publication, audited corrections/restatements, OpenClaw financial cutover and portfolio calculations are separate tasks. Verification must establish source accuracy, units, scope and period compatibility. Portfolio integration requires confirmed security-to-issuer mapping; TTM must reject incompatible or overlapping periods. Missing facts remain missing. ([Architecture boundary](../backend/src/investor_platform/financial_schema.sql))

## References

- [Schema](../backend/src/investor_platform/financial_schema.sql) — issuer, metric, period, source and observation contracts.
- [Importer](../backend/src/investor_platform/financial_import.py) — consistent snapshot, preservation, verification and conflict refusal.
- [Read/access helpers](../backend/src/investor_platform/financial_store.py), [CLI](../backend/src/investor_platform/financial_cli.py) — explicit credentials and read-only queries.
- [Synthetic tests](../backend/tests/test_financial_data.py) — import fidelity, WAL, rollback, identity and reader access.
