# Portfolio tracker calculations

## Scope

USD-settled long-only equities/ETFs, immutable recorded cash/trades, and daily closing observations. SPY and QQQ are investable S&P 500 and Nasdaq-100 proxies, not the index series themselves. Their fund costs and tracking differences remain in their returns. ([SPY](https://www.ssga.com/us/en/institutional/etfs/state-street-spdr-sp-500-etf-trust-spy), [QQQ](https://www.invesco.com/qqq-etf/en/home.html))

## Primary portfolio performance

Imported accounts marked `cash_method: purchase_shortfall` or `cash_method: recorded` use one whole-account time-weighted return (TWR), including cash and recorded dividend receivables. The recorded method applies after broker cash reconciliation; it does not infer new deposits. Purchase-funded reconstructions start with zero cash. Inferred deposits are active ledger records dated immediately before purchases that need more cash; they are assumptions about funding, not verified broker deposits. Sales and income already received provide cash for later purchases. The interface has no stock/account measurement switch for these accounts. Both index choices use the same portfolio values, cumulative return, CAGR, yearly returns and dates. ([Funding rules](../backend/src/investor_platform/funding.py), [funding synchronization](../backend/src/investor_platform/purchase_funding.py), [performance calculation](../backend/src/investor_platform/performance.py))

The standard whole-account income, price, FX and split checks below still apply. Inferred purchase funding does not reconcile missing dividends or certify the source history. Without an explicit dividend policy, missing or mismatched recorded dividend income withholds portfolio return and CAGR; provider dividends are never inserted as spendable cash. Other accounts retain their existing measurement controls.

## Legacy stock-sleeve measure

The **Stocks only** view measures the invested stock positions from recorded purchases, sales and share receipts. It is an estimated daily time-weighted stock return, not the return of the entire brokerage account. Idle cash, cash-currency translation, interest, lending income, withholding and account-level expenses are excluded. Native stock prices still use dated USD FX. Recorded trading fees remain in purchase costs and net sale proceeds.

For each session, link `(ending stock value + net sales + estimated gross dividends − close-valued share receipts) / (previous stock value + purchase costs)`. Purchases are treated as contributions at the start of the session and sale proceeds as withdrawals at its end. Gross distributions use provider ex-dates and prior-day quantities, regardless of when a broker pays cash. They are paid out of the measured stock sleeve; no cash or dividend records are created. Provider estimates may differ from actual broker distributions. This follows the same daily flow convention as the account calculation below, with the measurement boundary around stocks instead of all account assets.

The first displayed close is the baseline; first-day trading gains are excluded. With no invested capital and no purchases, the index stays flat; an in-kind receipt starts at its closing value. Later purchases restart measurement without erasing earlier returns. An empty stock selection is unavailable. Benchmarks use the same displayed dates and reinvest distributions. Excluding a stock removes its positions, trade capital and estimated distributions; it does not retain hypothetical idle cash. Both period controls preserve the selected measurement.

Missing prices, invalid listings and unsupported held-period splits still block this estimate. Incomplete trades and inferred opening shares still affect accuracy. Missing cash funding records do not block it because cash is outside this measurement. Choose **Whole account** to include cash and recorded income, with the reconciliation checks below. The selector never changes stored data or the trade scorecard. See [ADR 0007](decisions/0007-stock-performance-scope.md).

## Whole-account valuations and comparison

Portfolio value = recorded cash + recorded unpaid dividend receivables + shares × closing price. Unknown basis affects gains, not market value. Unknown prices prevent the report rather than creating zero-value holdings. Yahoo adjusted closes are used only for benchmark return ratios; they adjust for splits and distributions. Yahoo portfolio valuations reverse subsequent split adjustment, including splits after the requested report end. Tiingo fallback uses its already as-traded close without reversing splits again. ([Yahoo adjusted close](https://in.help.yahoo.com/kb/adjusted-close-sln28256.html))

The implementation geometrically links `(V_end + withdrawals − close-valued in-kind contributions) / (V_previous + cash deposits)` for each market session. Cash deposits are available at the beginning of the session; withdrawals occur at its end. Shares received without a trade are valued and neutralized at the session close because no opening execution price is recorded. Stock-exclusion cash substitutes preserve that same receipt timing. Trading and investment income are internal. Weekends/holidays roll into the next market session. This daily convention approximates flow-adjusted performance when intraday valuations are unavailable; it does not claim GIPS compliance. ([Portfolio Performance daily methodology](https://help.portfolio-performance.info/en/concepts/performance/time-weighted/), [GIPS handbook](https://www.gipsstandards.org/standards/gips-standards-for-firms/gips-standards-handbook-for-firms/))

The first available session establishes the baseline (its trading gain is excluded). Both benchmarks use the exact displayed start/end sessions. Nonmatching benchmark sessions, missing held-security prices, stale benchmark tails, zero prior value and invalid daily-flow factors block the report. Chart endpoints identify the actual closing-date window. Daily values remain in the API response; the interface shows the chart and yearly summary. Excess return is the percentage-point difference from the benchmark, **not risk-adjusted alpha**.

Record gross dividends/capital-gain distributions with their security, ex-dividend date and cash payment date. Dividend income enters portfolio value as a receivable on the ex-date, then transfers to cash on payment; the payment is not a second gain or an external contribution. A historical report includes recorded receivables whose cash payment occurs after its ending date. Interest and other investment income are recognized when posted and cannot offset a missing dividend.

Provider distributions on prior-day shares validate each security/ex-date, including dates before a full-history reporting period. Missing or mismatched amounts above one cent withhold portfolio return, including on provisional accounts. No income is invented or posted. Legacy unclassified income must be classified before returns are shown. Withholding tax is a separate expense, not a reduction of the gross dividend record. Special entitlements, missing provider events and foreign-currency accrual/settlement differences still require reconciliation; this does not certify corporate-action completeness. Benchmarks reinvest distributions; portfolio dividends remain receivables or cash unless a purchase is recorded. See [ADR 0006](decisions/0006-dividend-accrual.md).

An account explicitly marked `dividend_policy: unrecorded_zero` temporarily assumes zero for unrecorded dividends in its canonical whole-account calculation. Those missing events add no cash or receivables and do not withhold the return. Actual recorded dividends still count; mismatched, unmatched or unclassified income retains the reconciliation guards. The summary visibly states **Unrecorded dividends assumed zero** under both index choices. This account-specific assumption changes neither the primary TWR method nor the default strict policy for other accounts. ([Dividend validation](../backend/src/investor_platform/income.py), [performance calculation](../backend/src/investor_platform/performance.py))

Shares held across a provider-reported split block the report until split accounting exists. Provider identity, currency and instrument type are validated. Yahoo histories and, when configured, Tiingo fallback histories and dated FX are cached privately in PostgreSQL for 24 hours. All calculations use current ledger records. Report calculation time is retained in the API response; provider download times are retained in the cache. Provider data may be revised and is not automatically independently reconciled. Ledger changes and date changes clear old reports. No future session or intraday quote is presented as a completed close.

## Recent and full-history views

All portfolios open to **Full history**. Purchase-funded imports use the primary whole-account measure; ordinary accounts initially select **Stocks only**. **YTD** and **1 year** use existing ledger balances at the selected boundary. Purchase-funded accounts retain their selected dates and index choice when ledger records refresh. Their historical deposits remain in accounting; selecting a later window does not create new funding or bypass the income checks. YTD anchors to the prior year-end closing session; 1 year anchors to the close on or before the date one calendar year before the requested ending date. An account opened later starts at its first available close. Legacy recorded-baseline views require no price lookup for earlier closed positions, but their sale proceeds and original FIFO lots remain in accounting. Earlier missing income and split adjustments are not reconstructed in that legacy mode, so its opening balance remains provisional. Purchase-funded accounts fetch full history for both index choices to preserve funding and received-share benchmark consistency; earlier missing prices or income can still make a recent comparison unavailable. Dates remain editable. **Full history** retains inception reconciliation and can still fail if a delisted price series is unavailable. Neither mode replaces missing prices with zero or trade prices. See [ADR 0005](decisions/0005-recorded-period-baselines.md).

In a recorded-baseline view, exclusions apply within that period: prior trades remain, and excluded opening shares become cash at the first session close. The all-history trade scorecard and current holdings are independent of this choice.

## Funding reconciliation

A new transaction reconstruction has no opening-cash placeholder. It starts with zero cash and adds only the shortfall immediately before each purchase, after using preceding cash movements in effective-date and source order. A later same-day sale or deposit cannot fund an earlier purchase. Recorded trade amounts and existing cash records are retained. Opening/received shares do not create spendable cash. ([Import](../backend/src/investor_platform/import_transactions.py), [shortfall calculation](../backend/src/investor_platform/funding.py))

Existing portfolios require a reviewed migration: only explicitly selected opening-cash or deposit placeholders are voided; originals remain in correction history. The preview checks the active-record revision and confirms that holdings and basis stay unchanged. Later trades, cash entries and corrections recalculate generated deposits atomically under the account lock, using active cash records and preserved purchase order. Backdated records can change or remove earlier inferred deposits; the correction history remains. `funding_status` remains `inferred`. An unreviewed legacy reconstruction is not silently migrated. ([Migration and synchronization](../backend/src/investor_platform/purchase_funding.py))

Broker cash reconciliation changes the method to `recorded`, stopping purchase-funding automation. An incomplete review retains `funding_status: inferred` and withholds account return and CAGR; a complete funding review permits the ordinary account calculation. Both retain whole-account measurement and the explicit dividend policy, if any. This transition does not restore the legacy cash estimator. ([Cash reconciliation](cash-reconciliation.md))

Mark a reconstruction `reconciled` only after reviewing dated deposits/withdrawals, transfers within the portfolio boundary, income, fees, opening balances and closing cash. A current cash override cannot establish historical funding dates. Keep source rows, transfer matches and unresolved allocations in ignored private storage. Accounts entered directly use `recorded` funding status; that is not independent broker certification.

## International listings

ASX, TSX/TSXV, Stockholm main/First North and Warsaw (WSE) quotes are converted to USD using dated AUD, CAD, SEK or PLN exchange rates. USD OTC listings are also supported. The recorded USD purchase/sale amounts are never converted again. Foreign holidays use the last available local close (at most four calendar days old) with current-session FX; missing FX or stale prices block valuation. This is a daily-date convention, not synchronized intraday pricing across time zones. See [ADR 0004](decisions/0004-international-market-data.md) for identity and calendar rules.

Up to 128 securities are fetched with bounded concurrency. Histories unavailable from both providers and unrecorded splits still block comparisons; FX support cannot reconstruct missing market data.

## CAGR and stock exclusions

CAGR annualizes the geometrically linked, flow-adjusted cumulative return: `(1 + return) ** (365.25 / elapsed calendar days) - 1`. The actual first and last displayed sessions define elapsed days; this project uses an ACT/365.25 convention. It does not annualize the raw change in portfolio balance, which includes contributions. The same formula applies to SPY, QQQ and a valid scenario. A withheld cumulative return also withholds CAGR. Periods shorter than 365 elapsed days display no CAGR; this avoids presenting an extrapolated short-period return as annual performance. This follows GIPS guidance on avoiding sub-year annualization, without claiming compliance. ([GIPS partial-period guidance](https://www.gipsstandards.org/qadatabase/5001/))

Search by ticker or exchange in **Excluded stocks**, select multiple stocks, then compare. Selected stocks remain visible as removable selections when the search changes. Escape closes the selector; Clear exclusions removes all selections. The original portfolio stays visible; a fourth chart line and summary row show the hypothetical alternative. Whole-account exclusions retain cash; stock-only exclusions measure only the remaining stocks. Clearing exclusions and comparing restores the ordinary view. See [ADR 0002](decisions/0002-stock-exclusion-scenarios.md) for opening-position valuation, income attribution and funding rules. Hypotheticals never write ledger records, change real holdings or recalculate the trade scorecard.

## Index comparison modes

### Primary purchase-funded comparison

Purchase-funded accounts have two choices. **Buy and hold** shows SPY/QQQ adjusted-close returns between the displayed dates. **Match purchase funding** invests the canonical ledger's external deposits in each index at that session's adjusted close, includes close-valued share receipts once, and holds the index shares after stock sales. Existing sale proceeds fund later stock purchases without another external deposit or index purchase. Both benchmark funds reinvest distributions. After cash reconciliation, **Match deposits** uses the recorded deposits under the same rules. The matched view also shows index dollar values; it does not calculate another portfolio return or another deposit schedule. ([Funded index replay](../backend/src/investor_platform/funded_benchmarks.py))

Both the portfolio and funded indexes link daily factors using beginning-of-session cash deposits, end-of-session cash withdrawals, and close-valued share receipts. The index holds each new deposit as cash until its closing purchase. That cash earns no index price change on its purchase session, so contribution timing can affect the matched index's TWR as well as its dollar value. Its percentage return need not equal period-start buy and hold. The first displayed close establishes the baseline. A never-sold index simulation rejects recorded cash withdrawals rather than inventing index sales. A genuine opening-cash record also blocks only this deposit-matched simulation; ordinary account buy and hold remains available. Cash reconciliation accepts dated deposits, not a new opening balance. ([Shared daily return factor](../backend/src/investor_platform/performance_math.py), [funded index replay](../backend/src/investor_platform/funded_benchmarks.py))

### Legacy compatibility

Legacy inferred accounts with an identified opening placeholder retain the separate minimum-funding estimator until reviewed migration. It ignores that placeholder, estimates gross dividend cash on provider ex-dates, reuses sales, and accepts recorded deposits. It rejects recorded withdrawals, income and expenses. These are legacy modeling assumptions, not the primary account return or verified cash history. ([Legacy estimator](../backend/src/investor_platform/funding_estimate.py))

Other accounts retain **Match buys & sales**, which matches stock purchases and FIFO sales with separate index units. Sale proceeds leave the index sleeve; remaining invested value excludes withdrawn proceeds. Recorded-period comparisons seed existing holdings at the first displayed close. Stock-exclusion scenarios retain the original benchmark deployments. This compatibility mode does not change the new primary whole-account method. ([Matched index replay](../backend/src/investor_platform/matched_benchmarks.py))

## Chart dates

The chart retains its exact first/last closing dates and adds annual ticks for histories over two years, quarterly ticks for periods over six months, and monthly ticks for shorter periods. Short ranges without a calendar boundary use sampled session dates. Tick positions use the same session spacing as the return curves; mobile date text remains readable. Daily detail rows are not rendered.

## Yearly comparison

The table below the chart derives each year's return from the same daily cumulative series: `(1 + year-end cumulative return) / (1 + prior year-end cumulative return) - 1`. It does not subtract cumulative percentages or average daily returns. The first available session is used for an incomplete first year; a lone year-end baseline does not create a zero-return year. Current-year results with a prior year-end baseline are labelled YTD, and other incomplete periods are labelled partial. Exact closing dates are available on the year label.

SPY and QQQ remain total-return fund proxies for the S&P 500 and Nasdaq-100. The adjacent signed difference is always **portfolio minus benchmark**, in percentage points; positive is green, negative red. The same convention appears beside cumulative and annualized benchmark results. A scenario has its own yearly column; benchmark differences continue to refer to the original portfolio. Unknown portfolio returns leave differences unavailable while retaining known benchmark returns. An index starting at zero after a total loss has no defined subsequent percentage return.

## Trade scorecard

A trade episode begins with no shares and ends with no shares in the same security. Multiple purchases and partial exits remain one episode. The scorecard uses all recorded history, independently of the chart period.

- P&L sums FIFO realized sale gains after acquisition/disposal fees. Dividends are excluded from this trade statistic.
- Win rate = profitable closed episodes / closed episodes with known basis. Breakevens count in the denominator. Open and unknown-basis episodes are excluded and counted separately.
- Payoff ratio = mean positive dollar P&L / mean absolute negative dollar P&L. Both winners and losers are required; otherwise show unavailable, not infinity or zero.
- Unknown opening basis remains unknown through any episode containing such a sale.

These are project conventions; average-win/average-loss is a standard profit/loss statistic, but the episode definition and exclusion rules must accompany it. ([QuantConnect glossary](https://www.quantconnect.com/docs/v2/writing-algorithms/key-concepts/glossary))

## Hypothetical close-all scorecard

The scorecard toggle simulates selling every currently open position at its latest completed USD close. Quotes use the same listing and matching-date FX checks as current holdings. It adds detached in-memory sales, then runs the ordinary FIFO/flat-to-flat scorecard across the complete recorded history. Earlier partial sales remain part of each decision. Recorded closed decisions stay included; unknown-basis decisions remain excluded. Missing or stale quotes withhold the hypothetical result instead of dropping positions silently.

The UI shows the actual quote dates: this is not an executable intraday quote. New sale fees, slippage and taxes are omitted. No trade, cash balance, holding, or benchmark hit-rate record is changed. Switching back restores the recorded-only scorecard.

Post-mortem's full-history stock contribution response has a private process-memory cache for five minutes, capped at 16 reports. Every request still checks account ownership, dates, and the active ledger revision. The key includes the active ordered ledger IDs, listing identity evidence, account funding policy and currency, request parameters, completed market date, and the sorted revision timestamps for every workspace provider-cache entry. A correction, cancellation, new relevant transaction, price refresh, or date change therefore selects a new result. The result is stored under its pre-calculation price revision, so a concurrent refresh cannot label old prices as new. Reports with warnings or errors are not cached. This does not change the browser's `no-store` privacy policy; restarts discard cached responses.

## References

### Methodology
- [Portfolio Performance daily methodology](https://help.portfolio-performance.info/en/concepts/performance/time-weighted/) — beginning-of-day deposits and end-of-day withdrawals.
- [GIPS partial-period guidance](https://www.gipsstandards.org/qadatabase/5001/) — avoiding annualization for periods under one year.
- [GIPS handbook](https://www.gipsstandards.org/standards/gips-standards-for-firms/gips-standards-handbook-for-firms/) — cash-flow-aware return measurement and geometric linking.
- [QuantConnect glossary](https://www.quantconnect.com/docs/v2/writing-algorithms/key-concepts/glossary) — average win/loss and win-rate terminology.

### Market data and benchmarks

- [Purchase shortfall rules](../backend/src/investor_platform/funding.py) and [migration/synchronization](../backend/src/investor_platform/purchase_funding.py) — dated inferred deposits, preserved source order and correction history.
- [Transaction import](../backend/src/investor_platform/import_transactions.py) — zero opening cash and new import funding.
- [Performance calculation](../backend/src/investor_platform/performance.py) and [shared daily factor](../backend/src/investor_platform/performance_math.py) — standard whole-account return and income guards.
- [Funded index replay](../backend/src/investor_platform/funded_benchmarks.py) — canonical deposits invested at closes, never-sold index holdings and TWR timing.
- [Legacy minimum-funding estimator](../backend/src/investor_platform/funding_estimate.py) — compatibility assumptions before reviewed migration.

- [Matched index replay](../backend/src/investor_platform/matched_benchmarks.py) — project purchase, FIFO exit, return and dollar-gain conventions.
- [Yahoo adjusted close](https://in.help.yahoo.com/kb/adjusted-close-sln28256.html) — split/distribution-adjusted prices.
- [SPY fund](https://www.ssga.com/us/en/institutional/etfs/state-street-spdr-sp-500-etf-trust-spy) — S&P 500 benchmark exposure.
- [QQQ fund](https://www.invesco.com/qqq-etf/en/home.html) — Nasdaq-100 benchmark exposure.

Tiingo setup, private caching and historical exchange review are documented in [Operations](operations.md#historical-data-fallback). Dated in-kind receipts count as external contributions at market value; see [received shares](portfolio.md#received-shares).
