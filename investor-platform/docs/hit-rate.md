# Hit rate and payoff ratio

The user’s definition (Minerva project discussion, 2 October 2026) is **hit rate = percentage of investment decisions that outperform the market**. This differs from the existing **win rate = percentage of profitable closed decisions**. A gain of $50 can miss a matched market gain of $100; a loss of $50 can beat a matched market loss of $100. We retain both labels. Payoff ratio remains average positive dollar P&L divided by average absolute negative dollar P&L, after trade fees. It does not silently change to a benchmark-relative payoff metric. ([QuantConnect glossary](https://www.quantconnect.com/docs/v2/writing-algorithms/key-concepts/glossary))

## Counting decisions

Project convention: one decision is a complete flat-to-flat position in one security. Multiple purchases and partial exits stay within one decision, shared with the payoff scorecard. Count each decision once and equally, not once per sale or dollar invested. Open positions are excluded. All recorded history is used, independently of chart dates.

Calculate separate hit rates against SPY and QQQ, the existing S&P 500 and Nasdaq-100 fund proxies. Their adjusted closing-price ratios represent reinvested distributions and incorporate fund tracking differences. ([SPY](https://www.ssga.com/us/en/institutional/etfs/state-street-spdr-sp-500-etf-trust-spy), [QQQ](https://www.invesco.com/qqq-etf/en/home.html), [Yahoo adjusted close](https://in.help.yahoo.com/kb/adjusted-close-sln28256.html))

## Matched benchmark convention

For each purchase lot, hypothetically invest its actual cost including fees in each benchmark at that purchase date’s adjusted close. Each sale consumes FIFO portions of those lots, matching the ledger’s cost allocation. For an allocated purchase cost C bought on b and sold on s:

`benchmark gain = C × (adjusted_close[s] / adjusted_close[b] − 1)`

Sum these gains across the whole decision. Actual P&L is total net sale receipts minus total purchase costs. A hit requires actual P&L to exceed the matched benchmark gain. Both sides use the same allocated capital and holding periods. Benchmarks have no simulated brokerage fees; actual trade fees reduce actual performance. Intraday execution timestamps are unavailable, so benchmark entry/exit uses daily closes. This is an explicit project approximation, not an audited attribution standard.

Round the final excess dollars to cents, half-even, before classifying. Ties count in the denominator but are not hits. Missing/unevaluable decisions are excluded with reasons, not counted as misses. If none can be evaluated, show unavailable, not 0%. The decision table exposes the dates, actual P&L and excess dollars for both benchmarks.

## Data limitations

Opening positions are excluded even with known basis: their original acquisition dates are unavailable. A provider-reported distribution earned while holding shares excludes that decision because recorded income cannot yet be attributed to a stock. This avoids comparing price-only gains to benchmark total returns or inventing attributable dividends. Decisions spanning splits are excluded until split accounting exists. Trades today wait for completed prices. Unsupported listings, more than ten years of history, and missing matching trade-date sessions also prevent evaluation. Nontrading dates are never silently moved. Counts and reasons expose the resulting selection bias.

Market fetch failures withhold the hit-rate report and offer retry; the local payoff scorecard remains usable. No market-data fetch writes to the ledger. Reports clear when new entries are saved. Single-provider event/price coverage is unverified against an independent source and may be incomplete or revised; a missing event cannot prove no event occurred. Source and fetch time accompany results.

## References

### Project definition
- User-provided hit-rate/payoff definitions in this Minerva conversation, 2 October 2026 — metric intent; the book’s author/title and population statistics were not supplied or independently verified.

### Terminology and market data
- [QuantConnect glossary](https://www.quantconnect.com/docs/v2/writing-algorithms/key-concepts/glossary) — win-rate and average-win/loss terminology.
- [SPY fund](https://www.ssga.com/us/en/institutional/etfs/state-street-spdr-sp-500-etf-trust-spy) — S&P 500 exposure.
- [QQQ fund](https://www.invesco.com/qqq-etf/en/home.html) — Nasdaq-100 exposure.
- [Yahoo adjusted close](https://in.help.yahoo.com/kb/adjusted-close-sln28256.html) — distribution/split adjustment convention.
