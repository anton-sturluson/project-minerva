# Post-mortem: stock return contributions

The Post-mortem page explains the recorded stocks-only portfolio return, by year or across full history. It includes open and closed positions, estimated gross dividends and recorded trading costs, using the same USD prices and foreign-exchange rates as the performance chart. It does not include idle cash, cash FX, interest, lending income or account expenses. Portfolio selection remains account-specific; the analysis never changes records.

## Views

Full history defaults to **Dollar gains / losses**, ranking stocks by their summed USD investment gain over the complete measured history. Each year defaults to **Time-weighted contribution**, ranking stocks by linked percentage points. The Measure selector allows either view for any period; changing the year restores that period’s default. The summary, contributors, detractors and table all use the selected measure. Dollar gains remain available when percentage contributions are undefined.

Dollar gains answer which stocks added or lost the most money. Time-weighted contributions explain the return index: an early trade in a small portfolio can contribute many percentage points while producing a small dollar gain. Neither view is the stock’s share of net profit; those percentages become unstable when total net profit is close to zero.

## Calculation

For stock `i` and session `t`, calculate the investment gain:

`gain_i = ending stock value − previous stock value + net sales − purchase costs − market value of received shares + estimated ex-date dividends`

The common denominator is the previous stock portfolio value plus that session's purchase costs, matching the chart's beginning-of-session purchase / end-of-session sale convention. Divide each stock's gain by that denominator to obtain its daily contribution. A received position is neutralized at its closing value; its tax basis is not investment gain. With no capital or purchases, the return index stays flat and contributions are zero.

The project uses an explicit forward-linking convention: multiply each daily contribution by the portfolio growth factor **before that session**, relative to the selected period's baseline, then sum those contributions by security. Their sum equals the period's compounded stock return. Annual contributions start at the prior year-end close, or the first recorded close for a partial initial year. Full-history contributions start at the chart's initial close. Contributions from separate years must not be simply added to explain the full-history compounded result.

Daily investment gains also sum into a USD gain column. This includes marked-to-market changes and distributions; it is not the FIFO realized P&L of closed trade episodes. Percentage-point contribution reflects both exposure and timing, not the security's own return or its percentage share of total profit. Dollar gain and linked contribution can have opposite signs when gains and losses occur at different portfolio capital levels. Positive/negative rankings use the selected measure; all participating securities remain in the table, including flat results. Display rounding can produce small differences between rounded rows and the unrounded total. Attribution is withheld if unrounded contributions fail to reconcile.

## Interpretation and limits

Transactions-based attribution uses both holdings and trades to explain the evaluation period. Multiperiod attribution needs an explicit linking convention because simple sums of daily effects do not equal compounded returns. Different linking conventions can allocate compounding effects differently. The formula above is this project's convention, not a claim of a unique standardized decomposition. ([CFA Institute performance evaluation](https://www.cfainstitute.org/insights/professional-learning/refresher-readings/2026/portfolio-performance-evaluation), [CFA Institute attribution review](https://rpc.cfainstitute.org/research/foundation/2019/performance-attribution))

This is attribution of the portfolio's absolute stock return. It is not benchmark-relative selection/allocation attribution, and it is not the hypothetical return from deleting a stock; use the performance page's exclusion tool for that scenario. Missing market prices, unsupported splits and incomplete transactions retain the limitations of the underlying [performance calculation](performance.md). Unknown cost basis need not prevent contribution measurement when share history and market values are known. A period beginning after the return index reached zero has no defined percentage contribution; dollar gains can still be shown.

## References

- [CFA Institute: Portfolio Performance Evaluation](https://www.cfainstitute.org/insights/professional-learning/refresher-readings/2026/portfolio-performance-evaluation) — transactions-based attribution and performance evaluation.
- [CFA Institute: Performance Attribution, History and Progress](https://rpc.cfainstitute.org/research/foundation/2019/performance-attribution) — attribution objectives and multiperiod linking conventions.
- [Project performance methodology](performance.md) — stock measurement boundary, daily timing, estimates and market-data checks.
