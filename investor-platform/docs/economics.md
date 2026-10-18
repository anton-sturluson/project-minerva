# Economics under Research

Research → Economics shows a U.S. macro overview, market valuation measures and a household-cost drill-down. Charts read accepted PostgreSQL observations. Page requests never contact a publisher. Source dates, publication frequency and collection checks are distinct.

## Minimal storage

Migration 0015 adds only `economic_observations` and `economic_refresh_state`. The typed registry in `backend/src/investor_platform/economics/registry.py` owns source definitions, series IDs, units and cadence. No source, series, job-history or snapshot registry tables are added.

Observation rows contain exact decimal values or explicit missing flags and source provenance. A changed fact appends a revision; an unchanged observation is not copied after every check. Source refresh state records due times and recent outcomes. Raw files are saved by content hash in ignored local storage; back up this storage with the database. Provider corrections are ordered by accepted collection, not a claim to complete historical release vintages. See [ADR 0012](decisions/0012-store-economic-observations-under-research.md).

## Macro and valuation definitions

The measure selector opens one detailed native-frequency chart near the top of the page. Latest macro and valuation readings, household prices and source details remain in collapsed sections below it. Date controls start at the available displayed history bounds; custom date filters remain under the reader's control.

| Measure | Definition |
| --- | --- |
| Headline inflation | Twelve-month change in the unadjusted CPI-U index. Do not mix adjusted and unadjusted levels. |
| Core PCE inflation | Twelve-month change in BEA's adjusted price index excluding food and energy. Core PCE is not the Fed's formal total-PCE inflation target. |
| Real GDP growth | Published quarter-on-quarter annualized percentage growth. Do not annualize this reported rate again. |
| Unemployment | Adjusted unemployment percentage. This household survey measure differs from payroll jobs. |
| Payroll growth | Change in adjusted payroll levels, in thousands of jobs, plus a separately named trailing three-month average. |
| Real consumer spending | Twelve-month change in real personal consumption expenditure levels. A monthly level reported at an annual rate remains a monthly observation. |
| Policy rates | The lower and upper Fed target bounds, retained separately at reported effective dates. Each range remains in effect until the next reported change. |
| Ten-year Treasury | Daily ten-year constant-maturity market yield, percent per year. Holidays and absent observations remain gaps. |
| Mortgage rate | Freddie Mac weekly thirty-year fixed rate; keep its November 2022 methodology change visible. This is not a full housing-cost estimate. |
| Financial stress | Exact STLFSI4 remains unavailable until a permitted storage route is confirmed. A missing index is not zero stress; do not silently replace it with another measure. |
| Shiller CAPE | The publisher's ordinary monthly CAPE, distinct from its total-return CAPE. Preserve estimated-input and provisional-month notes. |
| Fed public-equity/GDP proxy | Quarterly `100 × public_equity_millions / (nominal_GDP_billions × 1000)`, matched by calendar quarter. The Fed equity aggregate includes fund shares; this is a defined Buffett-style proxy, not a universal total-market-cap ratio. |

Read-time calculations use accepted source observations and retain their exact input references and formula identifier. Signed values are valid for growth, payroll changes and stress; the household-price nonnegative rule must not be applied to these measures. Growth calculations use calendar periods, preserve missing inputs and require positive denominators. Policy bounds never become an invented midpoint.

Leading periods without enough earlier input history are calculation warm-up, not missing published growth observations. They are excluded from the displayed growth range. Missing values within established history remain visible gaps with their input period and source notes. October 2025 CPI is a genuine publisher gap caused by the lapse in appropriations; do not interpolate it or treat it as a failed import. ([BLS explanation](https://www.bls.gov/cpi/additional-resources/2025-federal-government-shutdown-impact-cpi.htm))

Quarterly source date keys can identify a quarter by its first day while the statistic describes quarter-end value. Show `Qn YYYY` and retain that distinction. The equity/GDP proxy uses annualized nominal GDP as published; do not divide GDP by four, combine different quarters, or interpolate daily ratios. Both component revisions can change the result. A current ratio does not reconstruct its historical publication vintage.

The proxy does not reproduce [LongtermTrends' Buffett indicator](https://www.longtermtrends.com/market-cap-to-gdp-the-buffett-indicator/). Its first chart uses the Wilshire 5000 with GDP, while its second uses a broader public-and-private-equity numerator. This platform uses the Fed's quarterly domestic public-equity series, including fund shares. Different equity coverage and observation dates produce different ratios. Keep the existing definition and identity; changing to a Wilshire or fund-excluded numerator would require a separately named, reviewed series.

Shiller workbook dates use `YYYY.MM`: a numeric `2026.1` denotes October, so retain two decimal month digits during parsing. Download the workbook linked from the [publisher page](https://shillerdata.com/), since its hosted attachment URL can change. CAPE is normalized to six decimal places for the existing database column; the original value and rounding rule remain in provenance, and the original workbook is retained. Preserve source notes rather than replacing the series with a purported live daily CAPE.

## Numeric source access

Prefer original publisher files for persisted values. FRED remains useful for series discovery and definition links, but its current full service terms contain broad database-storage restrictions; this collector does not assume that a public graph export or API key resolves those restrictions. A publisher being public does not by itself establish unrestricted redistribution rights. See the [FRED terms](https://fred.stlouisfed.org/legal/).

| Publisher | Source route |
| --- | --- |
| BLS | Public JSON for CPI-U `CUUR0000SA0`, unemployment `LNS14000000`, payroll levels `CES0000000001`, and the existing food-price IDs. |
| BEA | Original national-accounts workbooks for nominal GDP, published real GDP growth, real PCE and core PCE prices. Preserve each table's units and calendar frequency. |
| Federal Reserve | Original target-bound CSV, H.15 preformatted Treasury CSV and current Z.1 table CSV archive. The valuation numerator is `LM883164115.Q` in `csv/F51_1_s.csv`; its dictionary identifies millions of dollars at end-of-period market value. |
| Freddie Mac | The historical weekly workbook linked from its PMMS page. |
| Shiller | The ordinary CAPE column in the publisher-linked monthly workbook, with source notes. |
| EIA / USDA | Existing direct public source files and household definitions. |

The Z.1 table archive is a small collection of release tables; do not fetch its separate full-observation CSV archive, which expands to gigabytes. Read only the approved table entry and keep download/decompression bounds. Fed data-download routes are changing as the DDP is retired, so a failed or changed format must retain the last accepted observations rather than silently changing the measurement.

## Initial collection

Back up the intended database before migration. Run from `investor-platform/backend` with the target `DATABASE_URL` explicitly set:

```sh
uv sync --frozen
uv run --frozen alembic upgrade head
uv run --frozen investor-economics --provider all
```

The collector uses original publisher downloads described above, including the existing USDA Moderate-Cost and EIA weekly gasoline/diesel workbooks. `--force` requests another attempt before a source is due. `--import-dir` accepts the known research payload filenames for an explicit initial import; it is not an arbitrary document importer. Imported fixtures or historical files must not be presented as a fresh publisher check. Use synthetic data and an isolated database for tests.

Initial or incomplete BLS macro history is backfilled in bounded ten-year API windows, from each series' documented start. Do not request a series in a window before it exists. A full backfill through 2026 uses twelve requests; account for other BLS requests within its [unregistered daily limit of twenty-five](https://www.bls.gov/developers/api_faqs.htm). Normal macro checks revisit the latest six years. The existing source transaction keeps prior accepted data if any window fails.

Set `ECONOMICS_RAW_DIR` to an ignored private directory for source evidence. The default `data/economics` is relative to the process working directory. Never put source files or database exports in Git. Exact file names and CLI options are available with `uv run --frozen investor-economics --help`.

## Automatic checks within the platform

Set `INVESTOR_ECONOMICS_REFRESH=1` in the private deployment's environment and restart the API. This explicitly enables the source worker in Tailscale mode. Leave it off on synthetic development/test servers. The worker belongs to the API process, so automatic checks run while the platform is running. PostgreSQL due state survives restarts; advisory locks prevent concurrent workers from importing the same source at once. Failed collection retains the previous accepted observations and uses bounded retries. This is not a system cron installation or a new generic scheduling service.

The registry is the single source of truth for the implemented check schedule. The UI shows each source's publication description and our polling schedule separately. Conservative checks are intentional when the publisher provides no stable release date. Keep timestamps in UTC internally and use New York time for release-clock rules so daylight saving changes do not move the intended local check time.

## Publisher frequency

| Source | Publication cadence | Automated access |
| --- | --- | --- |
| BLS food prices and CPI | Monthly, with CPI on the publisher's listed dates at 08:30 Eastern. | Public JSON source. |
| BLS jobs | Monthly Employment Situation, 08:30 Eastern on listed dates. | Public JSON source. |
| BEA national accounts | Monthly spending/price observations and quarterly GDP observations, with revised releases. | Original workbooks; the collection registry distinguishes publication from polling. |
| Fed policy bounds / Treasury yields | Policy bounds change with decisions; H.15 yields are business-day observations. | Original Fed CSV sources. |
| Fed public equity | Quarterly Z.1 release, with historical revisions. | Original table archive. |
| Freddie Mac mortgage rate | Weekly, Thursday noon Eastern or the publisher's listed holiday shift. | Original PMMS workbook. |
| Shiller CAPE | Monthly observations; no fixed publication day confirmed. | Publisher-linked workbook; the latest month can be provisional. |
| STLFSI4 | Weekly observations ending Friday; publication is a different date. | Unavailable pending a permitted numeric-storage route. |
| USDA food plans | Monthly; no fixed release day/time confirmed. A weekly budget amount is still a monthly observation. | Enabled public XLSX source. |
| EIA fuel alternative | Weekly, normally Tuesday around 10:00 Eastern; listed holiday releases shift to Wednesday. Observations refer to Monday. | Enabled public XLS source; distinct from OPIS. |
| Fidelity balances | Quarterly, with variable publication lag; no forward fixed-date calendar confirmed. | Disabled until permitted recurring access exists. |
| Redfin mortgage payments | Exact WSJ export unresolved. Current public affordability data have monthly observations and quarterly releases. | Disabled until the matching principal-and-interest definition/export is confirmed. |
| Edmunds vehicle prices | Monthly observations appear in reports; exact monthly aggregate publication schedule is unconfirmed. Public reports are irregular/quarterly. | Disabled; open API ended and no matching complete feed was verified. |
| OPIS retail fuel | Daily public retail averages; exact entitled feed/cutoff depends on product. | Disabled without applicable access. |
| FactSet index comparison | Trading-day market observations; exact index variant and delivery time require the entitled feed. Quarterly chart sampling is not quarterly publication. | Disabled without an exact tested index contract. |

The platform does not automatically crawl disabled sources. Do not substitute their approximate public alternatives under the same series name.

## Measurement rules

- BLS household-price series are dollar prices, distinct from the macro CPI index. Preserve source-reported missing values and footnotes.
- USDA family budget uses a defined household and compatible component costs. Retain calculation inputs and source locations. Do not join different household definitions as if they were one series.
- EIA is an alternative to WSJ's OPIS series. Preserve gasoline and diesel coverage differences and methodology breaks. Weekly reference prices are not seven-day averages.
- Charts use calendar dates and visible gaps, with accessible tables. Reported period and last successful collection remain visible so an old value does not look current merely because a check succeeded today.

## Verification

Use the existing backend isolated-schema tests for migration/storage/API checks. Parsing tests must validate actual source fields, missing values, household calculations and malformed-input rejection. Storage tests must demonstrate duplicate-free replay, retained revisions, and failure preservation. Frontend checks cover navigation under Research, chart/table display, unavailable sources, empty/error states, keyboard access and narrow layouts. Never use real portfolio records as fixtures. See [operations verification](operations.md#verification).

## References

### Public source methods and schedules

- [BLS average prices](https://www.bls.gov/cpi/factsheets/average-prices.htm), [API contract](https://www.bls.gov/developers/api_signature_v2.htm), and [CPI release calendar](https://www.bls.gov/schedule/news_release/cpi.htm) — definitions, retrieval and monthly releases.
- [USDA monthly food-plan reports](https://www.fns.usda.gov/research/cnpp/usda-food-plans/cost-food-monthly-reports) — workbooks, household costs and monthly updates.
- [EIA fuel data](https://www.eia.gov/petroleum/gasdiesel/), [current release schedule](https://www.eia.gov/petroleum/gasdiesel/schedule.php), [gasoline methods](https://www.eia.gov/petroleum/gasdiesel/gas_proc-methods.php), and [diesel methods](https://www.eia.gov/petroleum/gasdiesel/diesel_proc-methods.php) — public histories, timing and coverage.

### Unavailable exact sources

- [Fidelity reports](https://about.fidelity.com/data-and-insights) and [terms](https://www.fidelity.com/terms-of-use) — quarterly reports and recurring-access restriction.
- [Redfin methods/calendar](https://www.redfin.com/news/data-center/methodology/) — quarterly affordability releases and payment components.
- [Edmunds access policy](https://help.edmunds.com/hc/en-us/articles/206103257-Accessing-Edmunds-data) — ended API and access limits.
- [OPIS retail products](https://www.opis.com/product/pricing/) — product-specific data delivery.
- [FactSet Formula API](https://github.com/factset/enterprise-sdk/blob/main/code/python/Formula/v1/docs/TimeSeriesApi.md) — entitled request contract, not proof of an exact index feed.

### Macro and valuation publisher sources

- [BLS CPI](https://www.bls.gov/cpi/) and [Employment Situation](https://www.bls.gov/news.release/empsit.nr0.htm) — CPI, unemployment and payroll definitions.
- [BEA national income and product accounts](https://www.bea.gov/itable/national-gdp-and-personal-income) — original GDP, PCE and price tables.
- [Fed H.15 downloads](https://www.federalreserve.gov/datadownload/Choose.aspx?rel=H15) — original preformatted Treasury rate package.
- [Fed Z.1 current release](https://www.federalreserve.gov/releases/z1/) and [table archive](https://www.federalreserve.gov/releases/z1/current/z1_csv_files.zip) — quarterly public-equity level and source dictionary.
- [Freddie Mac PMMS](https://www.freddiemac.com/pmms) — weekly mortgage rates and linked history.
- [Shiller data](https://shillerdata.com/) — ordinary and total-return CAPE definitions, workbook and data notes.
- [Buffett's original essay](https://www.berkshirehathaway.com/2001ar/FortuneMagazine%20DEC%2010%202001.pdf) — original publicly traded securities/GNP comparison; the implemented GDP proxy uses a different named definition.
- [LongtermTrends Buffett charts](https://www.longtermtrends.com/market-cap-to-gdp-the-buffett-indicator/) — distinct Wilshire and public/private-equity comparisons; these are not the platform's Fed public-equity series.
- [BLS 2025 shutdown impact](https://www.bls.gov/cpi/additional-resources/2025-federal-government-shutdown-impact-cpi.htm) — genuine missing CPI observations and collection limits.
