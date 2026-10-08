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

## Manager position changes

The manager detail groups positions by reported quantity: Increased includes new positions, Decreased includes exits, and Unchanged means the quantity is the same. Each group sorts by the absolute dollar change from largest to smallest, with security identity as the tie-breaker. Dollar change is current reported holding value minus previous reported holding value, so it includes market-price effects and is not trade cash flow.

Current 13F weight is current holding value divided by all disclosed current holdings value, including disclosed options and principal positions. It describes the reported 13F portfolio, not the manager's full fund. An exit has zero current weight when the current portfolio has a positive value; a zero-value portfolio has unavailable weights. Before/after fractions and their signed difference share one comparison calculation.

## Stock activity

Research has two subsections: Managers and Stock activity (`#research/activity`). The activity view compares all managers at one selected calendar quarter and the immediately preceding quarter. Its default is the newest quarter with a usable manager comparison; it does not combine each manager's latest, potentially different quarter. Coverage shows included managers and lists exclusions for missing, blocked, or zero-value snapshots.

The two rankings show shares increased (including new positions) and shares decreased (including exits). A manager contributes once per CUSIP and direction. Rankings exclude options and principal positions; share-type disclosures can also include funds. Unchanged quantities do not contribute, even when their value or weight changes. Share changes can reflect splits or reporting changes as well as trades.

Each ranking sorts by contributing manager count descending, then the signed average weight change: descending for increases, ascending for decreases, then CUSIP. The average gives each contributing manager equal weight and uses only the managers in that direction, not every covered manager. Weight change is current 13F weight minus previous 13F weight, shown in percentage points: 2% to 3% is +1 pp. Both fractions use all disclosed 13F value, including disclosed options and principal positions. An increased quantity can have a negative weight change; the signed result is retained.

The view shows the top 20 stocks in each direction first, with an option to show all results. Expand a stock to see its managers, before/after quantities and weights, and filing links. The same stock can appear in both rankings when managers disagree. Activity is calculated from stored snapshots through the shared comparison calculation; no duplicate activity table, opaque score, or network fetch is added.

## References

### SEC

- [Form 13F guidance](https://www.sec.gov/divisions/investment/13ffaq): disclosure scope, filing timing, and amendments.
- [EDGAR data APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces): submissions indexes and historical files.

### Implementation

- [Manager source checks](research-sources.md): primary sources for the catalog and known reporting transitions.
- [Research API](../backend/src/investor_platform/research.py): coverage and quantity comparisons.
- [Importer](../backend/src/investor_platform/research_sync.py): explicit catalog and SEC ingestion.
