# Portfolio tracker calculations

## Scope

USD-settled long-only equities/ETFs, immutable recorded cash/trades, and daily closing observations. SPY and QQQ are investable S&P 500 and Nasdaq-100 proxies, not the index series themselves. Their fund costs and tracking differences remain in their returns. ([SPY](https://www.ssga.com/us/en/institutional/etfs/state-street-spdr-sp-500-etf-trust-spy), [QQQ](https://www.invesco.com/qqq-etf/en/home.html))

## Valuations and comparison

Portfolio value = recorded cash + shares × closing price. Unknown basis affects gains, not market value. Unknown prices prevent the report rather than creating zero-value holdings. Yahoo adjusted closes are used only for benchmark return ratios; they adjust for splits and distributions. Portfolio share valuations use closes with subsequent split adjustment reversed, including splits after the requested report end. ([Yahoo adjusted close](https://in.help.yahoo.com/kb/adjusted-close-sln28256.html))

The implementation geometrically links `(V_end − net external flow) / V_previous` for each market session. Deposits/opening cash are positive external flows, withdrawals negative, and opening positions within the period are in-kind contributions at the session close. Trading and investment income are internal. Weekends/holidays roll into the next market session. All flows are assumed at the closing boundary; intraday timing is unavailable. This convention approximates flow-adjusted performance and does not claim GIPS compliance. GIPS distinguishes true time-weighted returns using valuations at appropriate flow boundaries. ([GIPS handbook](https://www.gipsstandards.org/standards/gips-standards-for-firms/gips-standards-handbook-for-firms/))

The first available session establishes the baseline (its trading gain is excluded). Both benchmarks use the exact displayed start/end sessions. Nonmatching benchmark sessions, missing held-security prices, stale benchmark tails, zero prior value and invalid closing-flow factors block the report. Daily rows and the baseline date make the measurement window inspectable. Excess return is the percentage-point difference from the benchmark, **not risk-adjusted alpha**.

Gross dividends/capital-gain distributions must be entered as investment income on their ex-dates. The tracker compares recorded daily income to provider distributions on prior-day shares, including dates before the selected period. Differences above one cent withhold portfolio return. No income is automatically invented or posted. This is a deliberately limited reconciliation: withholding taxes, payment-date receivables, interest mixed with dividends, special entitlement rules and missing provider events require further accounting. It is not evidence that every corporate action was captured. Benchmark distributions are reinvested; portfolio distributions remain recorded cash.

Shares held across a provider-reported split block the report until split accounting exists. Provider identity, currency and instrument type are validated. Histories are fetched on request, not cached or saved; source and report dates are displayed; fetch time is retained in the API response. **Single-provider data is unverified against an independent source and may be revised.** Ledger changes and date changes clear old reports. No future session or intraday quote is presented as a completed close.

## International listings

ASX, TSX/TSXV and Stockholm main/First North quotes are converted to USD using dated AUD, CAD or SEK exchange rates. USD OTC listings are also supported. The recorded USD purchase/sale amounts are never converted again. Foreign holidays use the last available local close (at most four calendar days old) with current-session FX; missing FX or stale prices block valuation. This is a daily-date convention, not synchronized intraday pricing across time zones. See [ADR 0004](decisions/0004-international-market-data.md) for identity and calendar rules.

Up to 128 securities are fetched with bounded concurrency. Delisted histories and unrecorded splits still block comparisons; FX support cannot reconstruct missing market data.

## CAGR and stock exclusions

CAGR annualizes the geometrically linked, flow-adjusted cumulative return: `(1 + return) ** (365.25 / elapsed calendar days) - 1`. The actual first and last displayed sessions define elapsed days; this project uses an ACT/365.25 convention. It does not annualize the raw change in portfolio balance, which includes contributions. The same formula applies to SPY, QQQ and a valid scenario. A withheld cumulative return also withholds CAGR. Periods shorter than 365 elapsed days display no CAGR; this avoids presenting an extrapolated short-period return as annual performance. This follows GIPS guidance on avoiding sub-year annualization, without claiming compliance. ([GIPS partial-period guidance](https://www.gipsstandards.org/qadatabase/5001/))

Select stocks under **Exclude stocks**, then compare. The original portfolio stays visible; a fourth chart line and summary row show the hypothetical cash alternative. Clearing exclusions and comparing restores the ordinary view. See [ADR 0002](decisions/0002-stock-exclusion-scenarios.md) for opening-position valuation, income attribution and funding rules. Hypotheticals never write ledger records, change real holdings or recalculate the trade scorecard.

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
- [GIPS partial-period guidance](https://www.gipsstandards.org/qadatabase/5001/) — avoiding annualization for periods under one year.
- [GIPS handbook](https://www.gipsstandards.org/standards/gips-standards-for-firms/gips-standards-handbook-for-firms/) — cash-flow-aware return measurement and geometric linking.
- [QuantConnect glossary](https://www.quantconnect.com/docs/v2/writing-algorithms/key-concepts/glossary) — average win/loss and win-rate terminology.

### Market data and benchmarks
- [Yahoo adjusted close](https://in.help.yahoo.com/kb/adjusted-close-sln28256.html) — split/distribution-adjusted prices.
- [SPY fund](https://www.ssga.com/us/en/institutional/etfs/state-street-spdr-sp-500-etf-trust-spy) — S&P 500 benchmark exposure.
- [QQQ fund](https://www.invesco.com/qqq-etf/en/home.html) — Nasdaq-100 benchmark exposure.
