# Shared financial database

The first increment provides a PostgreSQL financial-data namespace and a shared `investor-data` CLI. It prepares a copy alongside SQLite; it does not change OpenClaw skills, jobs, sessions or database settings. SQLite remains the live research workflow's store until a separate cutover. ([Importer](../backend/src/investor_platform/financial_import.py), [CLI](../backend/src/investor_platform/financial_cli.py))

## Data contract

The `investor_data` namespace contains five tables and a joined read view. Company, metric, period and observation IDs are preserved during import. Portfolio accounts, securities and transactions remain in their existing schema. ([Schema](../backend/src/investor_platform/financial_schema.sql))

| Table                | Purpose                                                                                                   |
| -------------------- | --------------------------------------------------------------------------------------------------------- |
| `companies`          | Issuer identity and existing company metadata. CIK and fiscal year end are nullable until confirmed.      |
| `metrics`            | Stable metric keys, definitions and value types; duration/instant basis can be assigned after review.     |
| `company_periods`    | Company-owned year, quarter and YTD periods with explicit fiscal labels and dates.                        |
| `sources`            | Document references, optional URLs, publication/retrieval dates and actual content hashes when available. |
| `metric_values`      | Decimal values or ranges, currency, missingness, scenario, qualifier, origin and provenance.              |
| `metric_values_flat` | Joined company, metric, period, observation and source fields for readers.                                |

One observation is canonical for each metric, period and scenario. Actuals, guidance, targets, consensus and estimates remain distinct. Missing figures stay missing. The import preserves legacy metric definitions and source references; it does not infer publication dates, document hashes or duration/instant classifications. Imported observations are `legacy_unverified`. Converting SQLite floating-point values to PostgreSQL `NUMERIC` preserves their available representation, without recovering precision already lost in SQLite. ([Importer](../backend/src/investor_platform/financial_import.py))

New observations use decimal strings, such as `"123.00000000000000001"`. Monetary values require a currency. Reported values need a source reference and locator; derived values need a calculation note. New facts are `unverified`, and the writer cannot mark its own work verified. The store does not yet implement source verification, restatement history or audited corrections. ([Validation and access](../backend/src/investor_platform/financial_store.py))

## Prepare the copy

Run from the independent backend project after `uv sync --frozen`. Set `INVESTOR_DATA_DATABASE_URL` through a private environment or secret manager. The CLI requires this variable explicitly and never falls back to portfolio administrator credentials. Do not put connection secrets in commands, checked-in files or agent prompts.

```sh
uv run investor-data inspect-sqlite --sqlite /private/path/invest.db
uv run investor-data migrate-sqlite --sqlite /private/path/invest.db
uv run investor-data verify-sqlite --sqlite /private/path/invest.db
```

The importer opens SQLite read-only and takes a consistent backup that includes committed WAL records. It imports only the four financial tables and derives source records from their existing references. News, prices, fund records and qualitative tables stay in SQLite. A successful import compares every migrated field and reports counts plus a snapshot digest; it does not print company records. ([Importer](../backend/src/investor_platform/financial_import.py))

Import and initialization run in one PostgreSQL transaction. An exact rerun is harmless; a populated target that differs is rejected without overwriting it. Unknown SQLite columns and an existing namespace without the expected version marker are rejected. The shared financial namespace has its own version marker because it is independent of portfolio Alembic migrations. Future schema changes require an explicit migration. ([Importer](../backend/src/investor_platform/financial_import.py), [Initialization](../backend/src/investor_platform/financial_store.py))

Keep the imported copy a staging snapshot while live SQLite continues to receive writes. Reconcile any changes before cutover; do not assume the snapshot remains current or enable competing production writers. To abandon preparation, stop using the new namespace and have its database owner remove only that namespace. SQLite remains intact.

## Read and append

```sh
uv run investor-data companies --ticker DEMO
uv run investor-data history --company-id 42 --metric-key revenue.total.reported
uv run investor-data append --input observation.json
```

History defaults to actuals and returns the latest bounded set in chronological order. Use `--scenario` to request estimates or guidance. `--schema investor_data_test_example` before the command selects a dedicated test namespace. ([CLI](../backend/src/investor_platform/financial_cli.py))

A synthetic `observation.json`:

```json
{
  "company_id": 42,
  "period": {
    "period_kind": "year",
    "fiscal_year": 2025,
    "fiscal_label": "FY2025",
    "period_start": "2025-01-01",
    "period_end": "2025-12-31"
  },
  "observations": [
    {
      "metric_key": "revenue.total.reported",
      "value": "123.00000000000000001",
      "currency_code": "USD",
      "source": {
        "reference": "Synthetic FY2025 report",
        "url": "https://example.com/fy2025",
        "published_on": "2026-02-01"
      },
      "source_locator": "Income statement, page 1"
    }
  ]
}
```

The company and metric must already exist. Append can create fiscal periods and sources. An exact retry returns the existing observation; conflicting values or metadata fail atomically. There is deliberately no agent command to replace canonical observations or administer company/metric definitions. ([Append implementation](../backend/src/investor_platform/financial_store.py))

## Database access and agent rollout

A database administrator creates dedicated non-administrator roles and calls `grant_access` with the chosen namespace and reader/writer names. Names must use `investor_data_reader` and `investor_data_writer` prefixes. The reader receives schema usage and SELECT. The writer additionally receives INSERT on periods, sources and permitted observation columns, plus the two required identity sequences. Neither receives UPDATE, DELETE, verified-state writes, company/metric writes or portfolio-table privileges. Use fresh roles without inherited broad privileges; this helper grants access and does not revoke unrelated existing grants. ([Access implementation](../backend/src/investor_platform/financial_store.py))

Before configuring live OpenClaw, run a headless agent against a synthetic namespace with separate temporary credentials. Verify lookup, exact decimal reads, append, retries, conflict refusal and read-only write refusal. Independently inspect the resulting records and remove the temporary schema/roles. Compare live configuration and job definitions before and after. Synthetic migration and role checks also run in the backend test suite. ([Tests](../backend/tests/test_financial_data.py))

A later cutover must reconcile the current SQLite financial tables, update the company-metrics skill and boot instructions, route financial work through the shared CLI, and retire writes to the migrated financial tables. The general SQLite workflow continues to own the other tables. Do not change live jobs or freeze SQLite as part of preparing this copy.

Portfolio financial profiles, TTM calculations, issuer-to-security mapping, collection scheduling and the complete news/price migration are subsequent features. Financial statements remain issuer-level data; holdings and portfolio weights remain portfolio-owned. ([Portfolio model](../backend/src/investor_platform/models.py))

## References

- [Financial schema](../backend/src/investor_platform/financial_schema.sql) — tables, constraints, provenance and read view.
- [Financial importer](../backend/src/investor_platform/financial_import.py) — read-only snapshot, preservation, verification and rerun behavior.
- [Shared store](../backend/src/investor_platform/financial_store.py), [CLI](../backend/src/investor_platform/financial_cli.py) — validation, reads, append and restricted access.
- [Synthetic tests](../backend/tests/test_financial_data.py) — migration, rollback, precision, permission and error behavior.
- [Portfolio model](../backend/src/investor_platform/models.py) — separate portfolio ownership.
