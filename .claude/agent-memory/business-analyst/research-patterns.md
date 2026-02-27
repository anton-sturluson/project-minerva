# Research Workflow Patterns

## 5-Phase Workflow

### Phase 1: Parallel Search (delegated to search agents)
Launch multiple search agents in parallel — one per discrete topic. Each agent saves sources to `hard-disk/reports/{TICKER}/research/{topic-slug}/`.

Research dimensions to consider (adapt to the company):
1. Business model & revenue streams
2. Industry & competitive landscape (including 7 Powers framework data)
3. Leadership & governance
4. Financial performance (LTM preferred)
5. Risk assessment
6. Growth catalysts & key initiatives (present impact, future impact, execution risks)
7. Recent news & sentiment
8. Valuation & peer benchmarking (LTM and NTM multiples, 4-6 comps)

Not a fixed count — launch additional search agents later if gaps emerge after reviewing initial results.

### Phase 2: Extract & Synthesize
List `research/` directory to discover topics. Read manifests, triage sources, extract with extract agents, build `context.md`, identify and fill gaps.

### Phase 3: Data Structuring
Structure raw data into CSVs at `hard-disk/reports/{TICKER}/data/`:
- `income_statement.csv` — 3-5 years: revenue, margins, EBITDA, SBC
- `balance_sheet.csv` — recent + 1-2 historical: assets, debt, cash, shares
- `cash_flow.csv` — 3-5 years: OCF, capex, FCF, buybacks
- `revenue_segments.csv` — segment revenue over time
- `peer_comps.csv` — ticker, multiples (LTM + NTM), growth, margins

Also save `sources.md` grouped by: SEC Filings, Earnings Releases, Financial Data Providers, Industry Research, News & Analysis.

### Phase 4: Analysis Script & Visualizations
Write `analyze_{ticker_lower}.py` that:
1. Reads CSVs from `data/`
2. Computes derived metrics (growth rates, margins, ratios)
3. Runs valuations via `minerva.valuation` (run_dcf, run_comps, run_reverse_dcf, run_sotp, dcf_sensitivity_matrix)
4. Generates matplotlib charts as PNGs (150+ DPI, `bbox_inches="tight"`)

Chart guidance: plot every key 10-K/10-Q metric showing a meaningful trend, plus any metric important to the investment thesis narrative. Three valuation charts always required: sensitivity heatmap, football field, peer comparison.

### Phase 5: Report Generation
Write `report.md` with 11 sections, embedding PNGs inline. Charts go where the reader needs them (financial trends in Section 5, segments in Section 2, valuation in Section 10, etc.).

## Effective Search Queries by Dimension
- **Revenue breakdown**: "{ticker} revenue segment breakdown {year}"
- **Margins**: "{ticker} gross margin operating margin adjusted EBITDA margin trend {year-2} {year-1} {year}"
- **Balance sheet**: "{ticker} balance sheet cash debt total assets {year}"
- **Cash flow**: "{ticker} cash flow free cash flow operating {year}"
- **Competitors**: "{ticker} competitive landscape {competitor names} market share {year}"
- **TAM**: "{ticker} total addressable market TAM size {year}"
- **Leadership**: "{ticker} CEO {name} leadership team board directors {year}"
- **7 Powers / moat**: "{ticker} competitive advantage moat switching costs network effects"
- **Analyst consensus**: "{ticker} analyst ratings price target consensus {year+1}"
- **Insider activity**: "{ticker} insider trading insider ownership {year} institutional holders"
- **Recent news**: "{ticker} recent news developments {current month} {current year}"
- **Peer multiples**: "{ticker} comparable companies peer comparison EV/Revenue EV/EBITDA {year}"
- **Valuation**: "{ticker} valuation DCF price target fair value analysis {year}"
- **SBC**: "{ticker} stock based compensation dilution shares outstanding {year}"
- **Key initiatives**: "{ticker} new products growth strategy expansion plans {year}"

## LTM vs NTM Rules
- Default to LTM (Last Twelve Months) for all metrics, ratios, and multiples.
- Use NTM only when projections add value: DCF inputs, reverse DCF implied growth, companies with inflecting earnings.
- Comps tables: show BOTH LTM and NTM columns. Weight LTM in commentary.

## Valuation Workflow
1. **Peer selection**: Pick 4-6 comps with genuine business model overlap. Write 2-3 sentences per peer justifying the comparison and flagging differences.
2. **Comps**: Gather LTM multiples (primary) and NTM (secondary) for all peers, derive median/mean, apply to subject.
3. **DCF**: Use `minerva.valuation.run_dcf()` with conservative assumptions. Explain each assumption (growth deceleration rationale, margin path vs. mgmt targets, WACC derivation via CAPM, terminal growth vs. GDP).
4. **SBC haircut**: Always subtract SBC as real economic cost — never ignore it for high-growth tech.
5. **Sensitivity**: Use `dcf_sensitivity_matrix()` to generate WACC vs. TGR grid. Annotate bull/base/bear cells.
6. **Reverse DCF**: Show what growth the market prices in and discuss if it's achievable.
7. **SOTP**: Use for multi-segment businesses to reveal hidden value or conglomerate discount.
8. **Commentary**: Layer on 1-2 paragraphs of analytical discussion per method explaining why the numbers make sense (or don't).

## 7 Powers Framework
For each of Hamilton Helmer's 7 powers, assess barrier + benefit:
- **Scale Economies**: Cost per unit declining with scale? Minimum efficient scale?
- **Network Effects**: Product value increasing with users? Direct or indirect?
- **Counter-Positioning**: Strategy incumbents can't copy without self-damage?
- **Switching Costs**: Financial, procedural, relational costs of switching?
- **Branding**: Price premium or CAC reduction from brand equity?
- **Cornered Resource**: Preferential access to talent, IP, licenses, data?
- **Process Power**: Deeply embedded processes hard to replicate?

Be honest — if a power is Weak or Absent, say so. Also identify advantages outside the framework.

## Sector-Specific Notes

### Vertical SaaS / Payments
- Gross margin misleadingly low due to payments pass-through revenue
- Key metric: "recurring gross profit" (SaaS + fintech GP)
- Adj. EBITDA margin measured against recurring GP, not total revenue
- SBC dilution critical — compute SBC as % of market cap
- Hardware is a loss leader — focus on payback period economics

### Restaurant Technology
- ~1M addressable U.S. restaurant locations
- 15-20% annual restaurant failure rate requires constant gross additions
- Thin margins (3-9%) make restaurants sensitive to macro
- Payment volume (GPV) is leading indicator for fintech revenue
- ARPU expansion from product attach rates, not pricing increases
