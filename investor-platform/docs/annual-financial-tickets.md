# Annual portfolio financial metrics: first three tickets

The approved first release uses reported financial statement inputs. Owner earnings, TTM, deterministic collection and the full SQLite cutover remain later work. These are local ticket drafts; no issues have been created in an external tracker.

## 1. Define the annual financial-data contract

Specify issuer identity, fiscal periods, source evidence, immutable restatements, missingness and metric definitions. Include reported earnings/EPS, cash-flow inputs, capex and share counts, with deterministic margins and per-share calculations. Deliver a reviewed [contract](annual-financial-contract.md), machine-readable bundle schema and synthetic example. No live database change is part of this ticket.

Done when the contract is reviewed, its example validates, and all three collectors can use the same definitions.

## 2. Collect and validate GOOGL, OSCR and ACFN annual financials

Blocked by ticket 1. Run three subagents in parallel, one per issuer, to collect FY2023–2025 from original filings. Use the shared bundle contract and keep downloaded sources with the pilot report. Implement validated PostgreSQL import and company-level reads. Preserve source locations, gaps and applicable metric definitions; handle Alphabet share classes, insurer applicability and Acorn's reporting scope.

Done when all nine issuer-year bundles have either verified facts or explicit gaps, accepted facts can be read from the shared store, and each company-level output has citations. Agent output alone is not verification.

## 3. Produce the weighted annual portfolio report

Blocked by ticket 2. Combine accepted facts with holdings at 31 December and dated equity market values, excluding cash. Show weighted margins, coverage for each metric and company-level earnings/EPS/cash-flow details. Do not average nominal EPS or company dollar earnings. Withhold aggregates when portfolio valuations are incomplete. Preserve the input versions, actual quote/FX dates and formula version needed to reproduce the report.

Done when the three-company pilot report reconciles to its company inputs and portfolio weights, shows source links and missing-data reasons, and can be reproduced from saved inputs.

## Order

Ticket 1 → ticket 2 (three parallel collectors) → ticket 3.
