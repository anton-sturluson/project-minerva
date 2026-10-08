# Research manager directory

The Research view reads a PostgreSQL manager registry with official websites, public letter or commentary sources, and SEC filing links. The reviewed [catalog](../backend/src/investor_platform/research_managers.json) includes established technology and growth investors plus clearly identified history candidates. See [source verification](research-sources.md).

## Load the registry and holdings

Use the independent backend project and its existing database configuration. Apply migrations before importing:

```sh
cd investor-platform/backend
uv run --frozen alembic upgrade head
uv run --frozen investor-research-sync --catalog-only
```

SEC collection requires `EDGAR_IDENTITY` set to a descriptive name and valid contact email. Keep the real contact in local environment configuration, never in committed files. Then load one manager or all catalog managers:

```sh
uv run --frozen investor-research-sync --manager altimeter --start-year 2016
uv run --frozen investor-research-sync --start-year 2016
# Revalidate previously blocked filings after a parser fix or source review.
uv run --frozen investor-research-sync --manager whale-rock --start-year 2016 --retry-blocked
```

Imports are explicit, paced, and idempotent by manager and accession. An explicit blocked-filing retry retains the prior import evidence and replaces normalized rows atomically; complete filings stay unchanged. The API does not fetch SEC data during page requests. Registry loading updates public metadata without deleting filing records. Holdings are independent of portfolio transactions. SEC XML responses are parsed in memory; normalized evidence is stored in PostgreSQL, with source links retained. No downloaded XML files are saved.

## Interpret coverage and changes

- The history reference gives the earliest sourced filing period or an explicit missing-history status. It does not prove continuous quarterly coverage.
- Verified ten-year coverage requires at least 40 consecutive usable imported quarters ending at that manager's latest loaded quarter. The displayed last quarter shows how current the imported record is.
- Comparisons use adjacent calendar quarters. Missing or blocked snapshots make the comparison unavailable.
- New positions, increases, reductions, and exits refer to changes in disclosed share or principal quantities. Price movement alone does not imply a purchase or sale. Splits and reporting changes can also change quantities. Quarter-end changes do not provide transaction dates, execution prices, or motives.
- CUSIP, option type, and share/principal type identify each position. Security-class descriptions remain display metadata because the text can change. Tickers are not guessed from company names.
- Amendments retain separate accession provenance. Uncertain amendments block comparison until resolved.
- Thirteen-F disclosures are a subset of a manager's investments. A long filing record is not a verified investment return record or a guarantee of reliable ideas. See the [SEC's Form 13F guidance](https://www.sec.gov/divisions/investment/13ffaq).

## References

### SEC

- [Form 13F guidance](https://www.sec.gov/divisions/investment/13ffaq): disclosure scope, filing timing, and amendments.
- [EDGAR data APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces): submissions indexes and historical files.

### Implementation

- [Manager source checks](research-sources.md): primary sources for the catalog and known reporting transitions.
- [Research API](../backend/src/investor_platform/research.py): coverage and quantity comparisons.
- [Importer](../backend/src/investor_platform/research_sync.py): explicit catalog and SEC ingestion.
