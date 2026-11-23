# Research

The Research view reads a PostgreSQL manager registry with official websites, public letter or commentary sources, and SEC filing links. The reviewed [catalog](../backend/src/investor_platform/research/managers.json) includes established technology, growth, and value investors with imported filing coverage. See [source verification](research-sources.md).

## Load the registry and holdings

Use the independent backend project and its existing database configuration. Apply migrations before importing:

```sh
cd investor-platform/backend
uv run --frozen alembic upgrade head
uv run --frozen investor-research-sync --catalog-only
```

`investor-research-sync` fetches SEC filings, parses the 13F XML, and saves normalized holdings and source evidence in PostgreSQL. `--start-year` includes report quarters on or after January 1 of that year; it defaults to the current year minus ten. Run `uv run --frozen investor-research-sync --help` for options.

SEC collection requires `EDGAR_IDENTITY` set to a descriptive name and valid contact email. Keep the real contact in local environment configuration, never in committed files. Then load one manager or all catalog managers:

```sh
uv run --frozen investor-research-sync --manager altimeter --start-year 2016
uv run --frozen investor-research-sync --start-year 2016
# Revalidate previously blocked filings after a parser fix or source review.
uv run --frozen investor-research-sync --manager whale-rock --start-year 2016 --retry-blocked
```

Each manager result reports `complete_filings` and `blocked_filings` across the requested report-period scope, including previously saved and newly imported filings. Original filings and amendments count separately; these counts do not measure usable quarter comparisons. `imported_filings` remains the number imported or retried in this run. Skipped or failed manager results also show the stored counts.

Imports are explicit, paced, and idempotent by manager and accession. An explicit blocked-filing retry retains the prior import evidence and replaces normalized rows atomically; complete filings stay unchanged. The API does not fetch SEC data during page requests. Registry loading updates public metadata without deleting filing records. Holdings are independent of portfolio transactions. SEC XML responses are parsed in memory; normalized evidence is stored in PostgreSQL, with source links retained. No downloaded XML files are saved.

Source total checks retain the reported cover total, raw information-table row count, summed row values, reporting unit, difference, and rounding bound. A cover-value mismatch does not block holdings, comparisons, or activity and does not add a user-facing warning. Holdings and portfolio weights use the reported rows, without changing their values to match the cover. Differences within `(raw row count + 1) / 2` reporting units are recorded as `consistent_with_rounding`; larger differences remain in the stored evidence as `outside_rounding_limit`. Neither classification proves how the filer rounded. Row-count mismatches, invalid data, confidential omissions, and uncertain amendments still block comparisons. See the [reviewed filing examples](research-sources.md#reviewed-filing-reconciliation).

A `NEW HOLDINGS` amendment can repeat the entire existing snapshot before adding positions. The comparison removes the repeated rows only when every existing position is present and each normalized position field is identical. It then retains each new position once and keeps both accession sources. Changed or partially repeated existing positions remain blocked. The [First Eagle source review](research-sources.md#reviewed-filing-reconciliation) records this case.

## Ingest quarterly history with Minerva

From the repository root, use the main CLI with the existing database and SEC identity configuration:

```sh
uv run minerva sec ingest-13f --quarters 20 --through-quarter 2026-Q2
```

This collects 2021-Q3 through 2026-Q2, exactly twenty report quarters, for every investor already stored in the workspace database. The final quarter is explicit; the CLI does not guess which quarter has filed. Minerva delegates to the existing platform importer and parser, without adding or refreshing catalog records. Collection includes investors whose AUM is undisclosed.

Counts and fetched filing documents stay within the inclusive window; saved filings outside it are retained. Repeated runs skip saved accessions. Missing or blocked quarters remain explicit, and reporting entities are not automatically joined to fill gaps. The internal backend command accepts the same window with `--all-investors`; it cannot combine `--start-year` with `--quarters`.

## Manager selection and AUM

The reviewed catalog defines which managers are followed. AUM is informational metadata; its amount, disclosure date, or absence does not gate the directory, SEC collection, or stock activity. A sourced firm or adviser AUM figure is kept separate from the value of disclosed 13F holdings. For Form ADV, its date is the disclosure filing date rather than a separate valuation date. Page requests do not fetch or refresh AUM evidence.

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

### Annual net change

The manager view can compare a calendar year with the prior December 31 snapshot. The latest loaded year uses its latest quarter and shows the endpoint range, marked YTD until Q4 is loaded. Earlier years require Q4. Missing or blocked boundaries or intervening quarters make the annual comparison unavailable; there is no fallback to another year or reporting entity.

Annual results reuse the quarterly quantity and value calculation at the two boundaries. They show net change, not the sum of quarterly buys and sells: a position increased and later reduced to its opening quantity is unchanged for the year. Value changes include price effects; portfolio weights are calculated from the two endpoint portfolios, never summed. Filing links retain the evidence for the full interval. The annual API is `/api/research/managers/{slug}/annual-changes?year=2026`; the quarterly API is unchanged.

## Stock activity

Research opens Stock activity at `#research` or `#research/activity`, followed by Managers (`#research/managers`) and Economics (`#research/economics`). The activity view compares all managers at one selected calendar quarter and the immediately preceding quarter. Its default is the newest quarter with a usable manager comparison; it does not combine each manager's latest, potentially different quarter. Coverage shows included managers and lists exclusions for missing, blocked, or zero-value snapshots.

The two rankings show shares increased (including new positions) and shares decreased (including exits). A manager contributes once per CUSIP and direction. Rankings exclude options and principal positions; share-type disclosures can also include funds. Unchanged quantities do not contribute, even when their value or weight changes. Share changes can reflect splits or reporting changes as well as trades.

The activity API returns a deterministic order by contributing manager count, then signed average weight change and CUSIP. The stock table defaults to contributing manager count descending. Four stock columns are sortable: security name, manager count, average current weight, and average weight change. Quarter-average close and closing-price range are informational columns. Selecting a heading toggles direction; numeric columns start descending and security starts alphabetically. Sorting applies to all results before the display limit, and a quarter change restores the default order. The average gives each contributing manager equal weight and uses only the managers in that direction, not every covered manager. Weight change is current 13F weight minus previous 13F weight, shown in percentage points: 2% to 3% is +1 pp. Both fractions use all disclosed 13F value, including disclosed options and principal positions. An increased quantity can have a negative weight change; the signed result is retained.

The stock table shows ten stocks per direction first and reveals ten more at a time. Stocks start folded. Expanding a stock shows a full-width manager table with before/after quantities and portfolio weights, and weight change. Manager tables start with ten rows and reveal ten more at a time, ordered by current 13F weight descending, with manager name as the tie-breaker. Changing a sortable heading reorders the full set and resets the display to ten stocks. A quarter change restores the defaults. Folding a stock resets its manager table to ten rows. The same stock can appear in both rankings when managers disagree. Activity is calculated from stored snapshots through the shared comparison calculation. Market context loads separately for visible CUSIPs. Filing evidence remains in the activity API and stored records; the contributor table has no Sources column.

The activity API retains the contributor’s reported quarter-end price and date for compatibility; the manager table does not display them. This proxy is disclosed holding value in USD divided by disclosed shares: current-quarter values for a retained or new position, and previous-quarter values and date for an exit. A positive reference quantity is required; otherwise price and date are unavailable. It is not an execution price, purchase cost or sale proceeds, and never divides value change by share change. ([SEC Form 13F instructions](https://www.sec.gov/info/edgar/forms/form13f.pdf))

### Interactive activity charts

The activity overview joins the full increased and decreased cohorts by CUSIP, retaining separate security classes. Left bars count managers with reductions or exits; right bars count managers with increases or newly reported positions. The default order is the sum of both counts descending, with CUSIP as the tie-breaker. Directional orders retain both bars. Search covers issuer, class and CUSIP before the 10/20-security display limit. The symmetric axis uses the full quarter's largest directional count and stays fixed while controls change. Unchanged quantities are excluded; reported quantity changes can include corporate actions and reporting changes, not only trades.

Selecting a chart row opens both contributor groups, before/after shares and weights, and filing links. Keyboard activation focuses the detail heading; Close or Escape returns focus to the row. Quarter changes and controls that remove the selected row clear its details. The existing tables retain independent sorting, pagination and market context.

The quarterly manager view reuses the same chart layout for reported portfolio-weight changes in percentage points, sorted by absolute change and position identity. It includes non-option share positions with a finite, nonzero API weight difference, including unchanged shares whose weights moved. Direction follows weight rather than share count. Weights retain the full reported 13F denominator, including disclosed options and principal positions. New positions and exits use the comparison delta only when available; a zero-value endpoint makes it unavailable. Chart details show the share-count status separately. This is allocation change, not trade cash flow. Annual views retain their existing position tables.

[The shared chart](../web/src/components/DivergingBarChart.tsx) owns the layout, accessible row controls and selected-detail focus; feature callers supply measurements, identity, ranking, labels and detail content. No chart library is required.

### Chart security labels

Chart rows use one line: `Issuer ($TICKER)`. Class and CUSIP remain in selected details and existing tables. `GET /api/research/activity/symbols?cusips=...` resolves at most twenty CUSIP/CINS identities through the same exact OpenFIGI resolver and one-day mapping cache used by market context. Every requested identity must occur as a positive, non-option share position in the workspace's stored research filings. This includes historical quarters for manager charts. Private portfolio records are not used.

The identity-only endpoint never fetches price history. Charts request symbols only for visible rows and keep names usable when mapping is unavailable; they do not guess symbols or render an empty ticker suffix. Unsupported stored identifiers keep their name-only labels without blocking valid identifiers in the same chart. Transport failures and temporary mapping outages are retried when rows are revisited, without an automatic retry loop; definitive no-match results remain cached. Share-class symbols retain the mapping's raw format, such as `ABC/A`, rather than price-provider spelling. The response retains mapping timestamp and composite FIGI evidence. It is a current US equity mapping, not proof of a historical ticker. Selecting or searching a chart does not add market-price requests.

## Stock market context

`GET /api/research/activity/market-context?quarter=2026-06-30&cusips=...` supplies independent market context for up to twenty ordinary-share CUSIPs already present in the workspace's selected or previous-quarter research filings. Existing activity quantities, weights, rankings and filing evidence remain unchanged. Options, principal positions and private portfolio records are not used for symbol resolution.

Exact CUSIPs and CINS identifiers are mapped through [OpenFIGI](https://www.openfigi.com/api/documentation), constrained to US, USD and Equity. All returned records must agree on one composite FIGI and one supported ticker; unmatched, ambiguous or unsupported mappings stay unavailable. A common-stock share-class ticker such as `ABC/A` remains unchanged in the API but is requested as `ABC-A` from price providers. The API retains the mapping timestamp and composite FIGI. This is a current identifier mapping, not proof of the historical listing identity or a manager's purchase cost. Mapping results, including unmatched and ambiguous results, use the existing one-day provider cache. Anonymous requests contain at most ten mapping jobs; provider quota failures return unavailable without an immediate retry loop.

The quarterly average is the arithmetic mean of available daily closing prices. Low and high are the minimum and maximum daily **closes**, not intraday low/high prices. USD equity or ETF history comes from the existing cached Yahoo adapter, with the existing configured Tiingo fallback and a supported US exchange check. First and last observed session dates and session count make coverage explicit; these do not guarantee a complete quarter. Prices are as traded in each session; a split can place different share units within one quarter. They are not split-normalized returns, transaction prices, a dollar-change/share-change ratio, or an estimate of cost basis. Missing or invalid history remains unavailable. History requests run with at most four workers per context request; mapping and price data remain separate from normalized SEC holdings.

## References

### SEC

- [Form 13F guidance](https://www.sec.gov/divisions/investment/13ffaq): disclosure scope, filing timing, and amendments.
- [Form 13F instructions](https://www.sec.gov/info/edgar/forms/form13f.pdf): reported values use quarter-end market valuation.
- [EDGAR data APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces): submissions indexes and historical files.

### Market data

- [OpenFIGI mapping documentation](https://www.openfigi.com/api/documentation): exact identifier filters, response identities and anonymous request limits.
- [Yahoo historical data](https://finance.yahoo.com/): observed daily closing prices through the existing adapter.
- [Tiingo end-of-day documentation](https://www.tiingo.com/documentation/end-of-day): configured fallback closing-price history.

### Implementation

- [Manager source checks](research-sources.md): primary sources for the catalog and known reporting transitions.
- [Research API](../backend/src/investor_platform/research/routes.py): coverage and quantity comparisons.
- [Research market context](../backend/src/investor_platform/research/market_context.py): exact public identity mapping and observed quarterly close statistics.
- [Importer](../backend/src/investor_platform/research/sync.py): explicit catalog and SEC ingestion.
