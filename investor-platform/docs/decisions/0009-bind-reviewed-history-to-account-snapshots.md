# 0009. Bind reviewed financial history to account snapshots

## Status

Proposed

## Context

Post-mortem needs the selected account's financial metrics for each held year. The annual observation store in [ADR-0008](0008-store-annual-financial-observations.md) accepts USD annual US GAAP facts. Reviewed history also includes native currencies, IFRS statements, and calculated LTM periods. Treating those records as annual US GAAP observations would change their meaning.

## Decision

Append independently reviewed history releases as immutable JSONB documents in the explicitly configured financial namespace. Each release contains five bounded measures, native units, traded-share conversion evidence, exact original packets, and review receipt hashes. Import validates references and hashes; requests read the stored release and do not read research files. This is a reviewed data release, not automatic source collection.

The account route checks ownership and values corrected holdings at year-end, or the latest completed market date for the current year. Cash and confirmed funds are excluded from company financials, including quote requests and the equity denominator. Companies without a metric remain in its coverage denominator. Missing company-security prices withhold the report and permit retry.

Native ratios need no currency conversion. Gross margin can use issuer-reported gross profit or clearly defined service-delivery costs; it must not infer direct costs from unallocated expense-by-nature totals. A material cost-basis limitation, such as separately reported depreciation excluded from costs of revenue, is retained as `basis_note` metadata and shown in the existing numbered footnotes. The history release keeps the legacy `basic_eps` key for company EPS: basic EPS is preferred; verified diluted EPS can be admitted when basic EPS is unavailable, with explicit `eps_basis: diluted` metadata and a matching company label. FCF/share uses issuer-reported or statement-derived consolidated cash flow with a documented cash-capex definition. Non-controlling interests alone do not exclude this company-level measure. Basic weighted-average shares are preferred; verified period-end ordinary shares or explicitly labeled diluted weighted-average shares can be used when basic shares are unavailable. The denominator and traded-share conversion must be source-backed; company-defined owner earnings and partnership-unit earnings do not silently replace these measures. By explicit user convention, a margin with verified zero revenue is admitted as 0% and includes the company's weight in the portfolio average. This is a convention, not division by zero. Each such metric must reference an exact-period, source-backed zero-revenue observation or calculation and carry a table note. Missing or negative revenue does not trigger this rule. Company-share amounts use verified traded-share units and dated USD FX. The headline prior column uses the prior year's actual holdings, weights, financial records, and dated FX. It equals the standalone prior-year headline; changing constituents does not block comparison. Company details retain same-company comparisons at the selected snapshot FX. Nonpositive prior amounts have no percentage change. These amounts remain weighted company averages.

## Consequences

The app can use reviewed history without weakening the annual store or adding account data to research releases. Imports remain explicit and source review remains necessary. Each request loads a bounded release document; collection and normalization updates still require a new reviewed import. Headline changes include changes in portfolio composition, company financials, and currency rates.

## Related ADRs

- Extends [ADR-0008](0008-store-annual-financial-observations.md): preserve the annual contract while admitting a separate bounded history release.
- Relates to [ADR-0003](0003-independent-holdings.md) and [ADR-0004](0004-international-market-data.md): use dated recorded holdings and verified listing prices.
