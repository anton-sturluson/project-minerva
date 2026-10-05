# Portfolio tracker calculations

## Scope

USD-settled long-only equities/ETFs, immutable recorded cash/trades, and daily closing observations. SPY and QQQ are investable S&P 500 and Nasdaq-100 proxies, not the index series themselves. Their fund costs and tracking differences remain in their returns. ([SPY](https://www.ssga.com/us/en/institutional/etfs/state-street-spdr-sp-500-etf-trust-spy), [QQQ](https://www.invesco.com/qqq-etf/en/home.html))

## Stock portfolio return (default)

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

Shares held across a provider-reported split block the report until split accounting exists. Provider identity, currency and instrument type are validated. Yahoo histories and, when configured, Tiingo fallback histories and dated FX are cached privately in PostgreSQL for 24 hours. All calculations use current ledger records. Report calculation time is retained in the API response; provider download times are retained in the cache. Provider data may be revised and is not automatically independently reconciled. Ledger changes and date changes clear old reports. No future session or intraday quote is presented as a completed close.

## Recent and full-history views

All portfolios open to **Full history**. Ordinary accounts select **Stocks only**; inferred-funding reconstructions select **Estimated buy & hold**. The following cash treatment applies to **Whole account**. **YTD** and **1 year** use recorded starting balances. YTD anchors to the prior year-end closing session; 1 year anchors to the close on or before the date one calendar year before the requested ending date. An account opened later starts at its first available close. Earlier closed positions require no price lookup, but their sale proceeds and original FIFO lots remain in accounting. Earlier missing income and split adjustments are not reconstructed in this mode, so the opening balance must be treated as provisional. Dates remain editable. **Full history** retains inception reconciliation and can still fail if a delisted price series is unavailable. Neither mode replaces missing prices with zero or trade prices. See [ADR 0005](decisions/0005-recorded-period-baselines.md).

In a recorded-baseline view, exclusions apply within that period: prior trades remain, and excluded opening shares become cash at the first session close. The all-history trade scorecard and current holdings are independent of this choice.

## Funding reconciliation

An inferred minimum opening cash balance is a bookkeeping placeholder, not evidence that all future capital was present at inception. Imported accounts default to `funding_status: inferred`, including legacy imports without a status field. Whole-account return, CAGR, excess returns and stock-exclusion scenarios are withheld in both full-history and recorded-period views. The stocks-only calculation is independent of these cash records. Benchmark curves remain available; any reconstructed closing value is explicitly estimated.

Mark a reconstruction `reconciled` only after reviewing dated deposits/withdrawals, transfers within the portfolio boundary, income, fees, opening balances and closing cash. A current cash override cannot establish historical funding dates. Keep source rows, transfer matches and unresolved allocations in ignored private storage. Accounts entered directly use `recorded` funding status; that is not independent broker certification.

## International listings

ASX, TSX/TSXV, Stockholm main/First North and Warsaw (WSE) quotes are converted to USD using dated AUD, CAD, SEK or PLN exchange rates. USD OTC listings are also supported. The recorded USD purchase/sale amounts are never converted again. Foreign holidays use the last available local close (at most four calendar days old) with current-session FX; missing FX or stale prices block valuation. This is a daily-date convention, not synchronized intraday pricing across time zones. See [ADR 0004](decisions/0004-international-market-data.md) for identity and calendar rules.

Up to 128 securities are fetched with bounded concurrency. Histories unavailable from both providers and unrecorded splits still block comparisons; FX support cannot reconstruct missing market data.

## CAGR and stock exclusions

CAGR annualizes the geometrically linked, flow-adjusted cumulative return: `(1 + return) ** (365.25 / elapsed calendar days) - 1`. The actual first and last displayed sessions define elapsed days; this project uses an ACT/365.25 convention. It does not annualize the raw change in portfolio balance, which includes contributions. The same formula applies to SPY, QQQ and a valid scenario. A withheld cumulative return also withholds CAGR. Periods shorter than 365 elapsed days display no CAGR; this avoids presenting an extrapolated short-period return as annual performance. This follows GIPS guidance on avoiding sub-year annualization, without claiming compliance. ([GIPS partial-period guidance](https://www.gipsstandards.org/qadatabase/5001/))

Search by ticker or exchange in **Excluded stocks**, select multiple stocks, then compare. Selected stocks remain visible as removable selections when the search changes. Escape closes the selector; Clear exclusions removes all selections. The original portfolio stays visible; a fourth chart line and summary row show the hypothetical alternative. Whole-account exclusions retain cash; stock-only exclusions measure only the remaining stocks. Clearing exclusions and comparing restores the ordinary view. See [ADR 0002](decisions/0002-stock-exclusion-scenarios.md) for opening-position valuation, income attribution and funding rules. Hypotheticals never write ledger records, change real holdings or recalculate the trade scorecard.

## Index comparison modes

### Estimated buy & hold

Accounts explicitly marked with inferred funding and a matching inferred opening
cash balance default to **Estimated buy & hold**. This estimates the fresh capital
needed by the original trading strategy and compares total estimated wealth with
never-sold SPY/QQQ holdings. It is a funding assumption, not verified deposit history.
The summary labels dollars **Estimated value (USD)** and the original account row
**Your portfolio + cash**. The header tooltip explains the funding and income policy;
the interface does not add explanatory paragraphs. ([Funding model](../backend/src/investor_platform/funding_estimate.py))

Start modeled cash at zero, ignoring only the explicitly identified inferred opening
placeholder. For each effective calendar date, add net sale receipts and estimated
gross stock dividends, subtract purchase costs, and inject fresh cash only for a
remaining shortage. Carry positive cash to subsequent dates. Same-day cash is netted
before mapping transactions to market sessions, so a Monday sale cannot fund an
earlier weekend purchase. Dividends use provider gross amounts on ex-dates, not actual
broker payment dates or after-tax amounts. Received assets contribute their first
session closing market value once, without becoming actual spendable cash. Every
fresh contribution buys SPY/QQQ at adjusted closing prices; benchmark distributions
reinvest and stock sales never sell benchmark holdings. ([Funding model](../backend/src/investor_platform/funding_estimate.py))

Actual estimated wealth is stock market value plus modeled cash. Both actual and
benchmark daily returns use `(ending wealth − close-valued asset receipts) / (previous wealth + fresh cash)`;
cash is available for the session and index purchases execute at the close. The first
displayed close establishes the baseline. Cumulative returns, CAGR and yearly results
use these same cash-inclusive return series; stock-only contribution attribution is
not reused. Full ledger replay is preserved for every reporting window, so selecting
YTD or a later start rebases returns but does not reset ending wealth or inferred
funding. Post-close transactions are excluded before security-price fetching.
([Performance endpoint](../backend/src/investor_platform/performance.py))

This mode rejects recorded cash movements/income anywhere in the replay history,
including dividends earned before the cutoff with later payment, because combining
those records requires a different funding policy. It rejects changed/real opening
balances, stock exclusions, and positive starting wealth without inferable capital.
Existing price/FX/split guards still apply. It creates no ledger records. Actual deposit
dates, missing broker cash income, tax withholding and intraday funding remain
unverified. The legacy comparisons remain selectable. ([Funding model](../backend/src/investor_platform/funding_estimate.py), [Integration checks](../backend/tests/test_funding_estimate.py))

### Existing comparisons

**Buy and hold** shows the existing SPY/QQQ adjusted-close
returns between displayed dates. **Match buys & sales** replaces both benchmark
series with independent, read-only index investments matching the original stock
deployments. It also updates the cumulative, annualized and yearly benchmark results
and their portfolio-minus-benchmark differences. ([Calculation](../backend/src/investor_platform/matched_benchmarks.py), [Performance endpoint](../backend/src/investor_platform/performance.py))

Each stock purchase invests its recorded USD cost, including recorded trading fees,
at that session's benchmark adjusted close. A sale exits the benchmark units attached
to the corresponding FIFO stock quantity, including partial lots; the hypothetical
index sale proceeds leave the measured sleeve. Actual stock sale dollars do not
determine the index withdrawal. Later purchases use their actual recorded amounts
as new contributions. Benchmarks reinvest distributions and charge no extra
simulated transaction fees. Non-session entries move to the next benchmark session,
consistent with the performance ledger convention. ([Matched index replay](../backend/src/investor_platform/matched_benchmarks.py))

The plot uses estimated daily time-weighted returns: daily factors are
`(ending index value + hypothetical sale proceeds − close-valued receipts) / (previous index value + stock purchase costs)`.
Purchase execution uses closing prices, so newly invested benchmark money has no
gain on its purchase session. An empty sleeve stays flat until reinvestment. With
continuous exposure and no added purchases, the percentage curve can equal buy and
hold despite different dollar amounts. In **Stocks only**, the matched comparison
shows an **Invested value (USD)** column for the original stocks, SPY and QQQ. The
index values are their remaining holdings after matching purchases and FIFO exits;
cash and exited proceeds are excluded, as the column tooltip states. They are not
the total wealth of a self-funded all-index account. The interface omits explanatory
paragraphs and the previous dollar-gain note; definitions remain here. A
whole-account index-value comparison would require explicit hypothetical cash
accounting and funding-shortfall checks. ([Matched index replay](../backend/src/investor_platform/matched_benchmarks.py), [Performance interface](../web/src/Tracker.tsx))

Full-history mode replays recorded stock purchases before rebasing to the displayed
first close. Opening/received shares with no acquisition date contribute their
closing market value when received. Recorded-period mode instead seeds the first
close with the actual market value of existing stock holdings and then matches new
purchases and sales. This does not infer earlier acquisition timing. Idle account
cash, interest and account expenses are excluded from these benchmark sleeves,
including when **Whole account** is selected. Exclusion scenarios retain the original
portfolio's benchmark deployments. Switching modes writes no ledger records and
preserves the selected period, measurement and exclusions. ([Matched index replay](../backend/src/investor_platform/matched_benchmarks.py), [Performance endpoint](../backend/src/investor_platform/performance.py))

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

## References

### Methodology
- [Portfolio Performance daily methodology](https://help.portfolio-performance.info/en/concepts/performance/time-weighted/) — beginning-of-day deposits and end-of-day withdrawals.
- [GIPS partial-period guidance](https://www.gipsstandards.org/qadatabase/5001/) — avoiding annualization for periods under one year.
- [GIPS handbook](https://www.gipsstandards.org/standards/gips-standards-for-firms/gips-standards-handbook-for-firms/) — cash-flow-aware return measurement and geometric linking.
- [QuantConnect glossary](https://www.quantconnect.com/docs/v2/writing-algorithms/key-concepts/glossary) — average win/loss and win-rate terminology.

### Market data and benchmarks

- [Minimum-funding model](../backend/src/investor_platform/funding_estimate.py) — assumed fresh contributions, dividend cash, never-sold index wealth and return boundaries.
- [Minimum-funding integration tests](../backend/tests/test_funding_estimate.py) — recycling, dividend reuse, receipts, calendar dates, cutoff and unchanged records.

- [Matched index replay](../backend/src/investor_platform/matched_benchmarks.py) — project purchase, FIFO exit, return and dollar-gain conventions.
- [Yahoo adjusted close](https://in.help.yahoo.com/kb/adjusted-close-sln28256.html) — split/distribution-adjusted prices.
- [SPY fund](https://www.ssga.com/us/en/institutional/etfs/state-street-spdr-sp-500-etf-trust-spy) — S&P 500 benchmark exposure.
- [QQQ fund](https://www.invesco.com/qqq-etf/en/home.html) — Nasdaq-100 benchmark exposure.

Tiingo setup, private caching and historical exchange review are documented in [Operations](operations.md#historical-data-fallback). Dated in-kind receipts count as external contributions at market value; see [received shares](portfolio.md#received-shares).
