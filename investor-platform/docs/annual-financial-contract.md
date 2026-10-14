# Annual financial observation contract

Status: pilot contract · 2026-10-14. This contract defines annual inputs and the bounded import/read path. Collection and portfolio reporting remain separate.

The pilot covers GOOGL, OSCR and ACFN fiscal years 2023–2025. Collect reported US-GAAP annual statement facts in USD. Use confirmed issuer identity; a ticker is a listing label, not a financial join key. Owner earnings, TTM, guidance, adjusted earnings and a generic collection platform are outside this contract.

## Bundle and evidence

Use the [JSON Schema](../backend/src/investor_platform/annual_financial_bundle.schema.json) and [synthetic bundle](../backend/tests/fixtures/financial/synthetic-annual-bundle.json). One bundle describes one issuer and one annual period. Every named input is present, with either a reported decimal value or an explicit missing/applicability status. Financial values are decimal strings in whole USD; share counts are unscaled decimal strings; EPS is USD per share. Exponents, numeric JSON values and formatted amounts are rejected. Ratios are derived as fractions and formatted as percentages only for display.

`bundle_id` identifies an immutable candidate/publication version. Sources include immutable document identity, HTTPS URL, original publication date, retrieval timestamp and the SHA-256 of the downloaded document bytes. Each reported fact names one source and an exact statement/row/column locator, with page or XBRL tag where available. Source documents can provide comparative prior-year facts; their publication date remains the date of that document. Do not invent an earlier date for a restated comparative value.

`period` carries actual start/end dates, fiscal year and issuer fiscal label. Annual flow inputs use the entire duration; the outstanding-share input is an instant at the same period end. A 52/53-week fiscal year is valid; a fiscal transition period needs an explicit policy before acceptance. Fiscal labels do not substitute for dates.

Collector filenames are `annual-bundle-FY2023.json`, `annual-bundle-FY2024.json` and `annual-bundle-FY2025.json` inside each issuer research folder. Each file is a candidate bundle, not a claim of accepted publication.

The synthetic source URL and hash are illustrative. The bundle demonstrates structure and arithmetic, not verification of real filing bytes.

## Input definitions

All duration inputs must describe the same issuer and annual period; each retains its stated entity scope. Scope is part of metric identity and cannot change between issuers or revisions.

| Key | Meaning and scope |
| --- | --- |
| `revenue` | Reported consolidated total revenue; do not substitute net premiums or a segment's sales. |
| `cost_of_revenue` | Reported consolidated cost of revenue, as a nonnegative accrual expense amount. Verify that it matches total revenue and covers the same period; do not substitute insurer medical claims as generic cost of revenue. |
| `gross_profit` | Reported consolidated gross profit. Do not invent a gross subtotal by relabeling an issuer-specific ratio. |
| `operating_income` | Reported consolidated operating income/loss. Preserve signed losses. |
| `net_income` | Consolidated net income/loss, including noncontrolling interests. |
| `net_income_common` | Net income/loss attributable to the parent's common shareholders, after applicable preferred claims. Do not substitute consolidated net income without evidence that the scopes agree. |
| `operating_cash_flow` | Consolidated net cash provided by/used in operating activities. Preserve signed cash outflows. |
| `cash_capex_ppe` | Cash purchases of property, plant and equipment, as a nonnegative outflow amount. Do not use purchases net of asset-sale proceeds, noncash additions or acquisitions. |
| `cash_capex_intangibles` | Separately disclosed cash investment in capitalized intangible assets/software, excluding acquisitions. Optional for initial calculations; retain an explicit status when not disclosed. |
| `basic_eps`, `diluted_eps` | Reported EPS attributable to common shareholders, including the reported class and split basis. Do not recompute or replace reported EPS. |
| `basic_weighted_average_shares`, `diluted_weighted_average_shares` | Reported annual basic/diluted weighted-average common shares on the stated class and split basis. Positive when present. |
| `period_end_common_shares` | Common shares outstanding at fiscal period end, with stated classes and split basis. Optional for initial ratios; not interchangeable with annual weighted-average shares or the cover-page count on a later date. |

For EPS and share counts, `share_basis.classes` identifies the represented share classes and `split_adjusted_through` states the date through which stock splits are reflected. The collector must inspect comparative figures for later split adjustments. For multiple classes, `share_basis.equivalence_note` records verified economic equivalence and `class_locators` identify the evidence in the same source. A singleton EPS value can represent multiple classes only when their reported EPS values agree. A share count can represent multiple classes only when the filing reports that combined denominator. A sum of separate class rows is a derived calculation outside reported facts, with the component input IDs and locators retained. If the filing has no reported compatible combined count, mark the bundle input unavailable and withhold the per-share result until a supported class-denominator calculation is added. The acceptance code must verify class rights and consistent split bases; a list of class names alone does not prove compatibility. For GOOGL, record the filing's actual class scope rather than assuming the traded Class A ticker covers the whole issuer.

Cash PP&E and intangible spending must be separate, non-overlapping categories. A combined capex number must not be labeled PP&E alone. Cash capitalized software included in a PP&E line cannot also enter the intangible input. Reclassifications and issuer-specific mappings need evidence before acceptance.

## Missing facts and applicability

`reported` requires a value, source and locator. `not_disclosed` means a supported source does not disclose this input separately. `not_applicable` means the measure does not apply under the agreed business definition. `unavailable` means collection could not establish it. Each absence requires a reason; add evidence for disclosure/applicability conclusions. Zero is a reported value only when the source supports zero. Omission, absence and missing capex are never zero.

OSCR is an insurer. Its filings define medical loss ratio using medical expenses relative to net premiums before ceded quota-share reinsurance, whereas total revenue includes other revenue categories. Therefore `1 − MLR` must not become this contract's gross margin. If the insurer presents no compatible gross-profit subtotal, mark `gross_profit` not applicable with filing evidence; do not count OSCR as covered for gross margin. Reported operating/net income and CFO can still be retained. Whether insurer CFO/FCF belongs in a common portfolio cash-margin comparison remains an explicit metric-applicability decision, separate from whether the cash-flow fact exists. ([Oscar 2025 10-K](https://www.sec.gov/Archives/edgar/data/1568651/000156865126000011/oscr-20251231.htm))

## Deterministic calculation contract

Calculate from accepted observation IDs; never accept a collector-supplied ratio as the authoritative result. Record formula version and exact input IDs when persisting a result. A missing input yields a missing result with a reason. Positive revenue and positive share denominators are required; signed earnings/cash numerators remain valid. Losses do not make margins zero or unavailable.

| Output | Formula and label |
| --- | --- |
| Gross margin | Reported `gross_profit / revenue`; if the subtotal is not disclosed, `(revenue − cost_of_revenue) / revenue` only after verifying compatible revenue/cost scope. The derived subtotal remains outside reported facts. Record which formula and input IDs were used. |
| Operating margin | `operating_income / revenue` |
| Net margin | `net_income / revenue`, explicitly consolidated. A common-shareholder net margin uses the separately named common numerator. |
| CFO margin | `operating_cash_flow / revenue` |
| FCF after cash PP&E capex | `operating_cash_flow − cash_capex_ppe`; this limited capex scope must appear in the label. |
| FCF margin after cash PP&E capex | The preceding FCF / revenue. |
| Allocated company CFO per basic share | `operating_cash_flow / basic_weighted_average_shares`, only for materially compatible common-class rights and split basis. Consolidated cash flow allocated per basic share is not cash attributable to common owners or an investor's look-through cash flow. |
| Allocated company FCF after cash PP&E capex per basic share | `(operating_cash_flow − cash_capex_ppe) / basic_weighted_average_shares`, under the same class/split compatibility gate as CFO per basic share. This remains allocated consolidated cash flow. |

The initial FCF requires no intangible input. Do not silently treat missing intangible spending as zero or describe this FCF as after all capital investment. A later FCF variant that also subtracts cash intangibles must require verified separate non-overlapping amounts. Do not add it in this increment.

Reported EPS can differ from net income divided by a generic share count due to class allocation, preferred claims and rounding. During a loss, reported diluted shares can equal basic shares because potential shares are anti-dilutive; do not add excluded shares. Per-share growth requires comparable annual durations, classes and split bases and is outside this first formula set.

For the synthetic bundle, expected fractions are gross margin `0.40`, operating margin `0.12`, consolidated net margin `0.09` and CFO margin `0.15`. FCF after cash PP&E capex is `12000000` USD, its margin is `0.12`, allocated CFO per basic share is `1.50` USD, and allocated FCF after cash PP&E capex per basic share is `1.20` USD. The reported common earnings/EPS use a separate numerator of `8000000` USD.

## Proposed PostgreSQL model

Use the existing backend's SQLAlchemy/Alembic migration owner and PostgreSQL service, with one `investor_data` namespace. Keep a bounded catalog rather than a second wide annual-statement store or unrestricted EAV system. The contract schema and catalog definitions must agree; new metric meanings require reviewed changes.

- **Company:** stable issuer key and verified public identifiers. Existing securities remain in the portfolio schema.
- **Period:** company, actual start/end, kind, fiscal year/label. Define duration and instant treatment explicitly.
- **Metric:** fixed key, unit, measurement basis and entity scope from this contract. Scope variants use different keys.
- **Source:** issuer, immutable document/revision identity, URL, publication/retrieval dates and content hash.
- **Publication:** immutable issuer-period bundle, accepted timestamp and referenced source versions. Revisions append; they do not rewrite accepted facts.
- **Observation:** publication, metric, decimal value or absence status, source locator and any class/split basis. A later snapshot references these stable IDs. A canonical view selects an accepted publication coherently for a company-period; it does not mix arbitrary newest cells across revisions.
- **Security mapping:** existing security ID to issuer ID, with confirmed class, instrument type and dated ADR conversion if relevant. Do not copy ledger records or portfolio quantities into the company fact store.

Derived-result records, when needed, must retain formula version and exact observation input IDs. A note alone cannot reproduce a calculation. The pilot commands below implement the bounded financial store. The retired SQLite migration remains outside this path.

## Acceptance beyond JSON Schema

JSON Schema validates fields, decimal syntax, supported keys, units, scopes and presence rules. Use a Draft 2020-12 validator with format checking. It cannot establish financial truth or all cross-record constraints. Acceptance code must check: unique source IDs; resolved fact source references; issuer consistency; start before end; publication/retrieval chronology; supported annual duration; verified document hash and locator; statement/class/split compatibility; explicit applicability; and no overlapping capex categories. A structurally valid bundle remains a candidate until these checks pass.

Preserve restated observations and original publication dates. The annual report's proposed default is retrospective: year-end holdings, fiscal years ending within the selected calendar year, and latest verified restatements. Label that policy. An as-known report selects only source versions published by its information cutoff; the database acceptance timestamp must not be substituted for publication date. Persisted reports pin holdings/quote/FX dates, input versions and formula version. Weighted ratios use each metric's covered market value and show coverage; dollar look-through totals and averages of nominal EPS are outside this contract.

## Pilot import and read commands

The backend now provides `investor-financial validate`, `import` and `show`. Run each with `--help` for its arguments. Successful operations emit clean JSON; errors go to stderr. Set `INVESTOR_FINANCIAL_DATABASE_URL` through private configuration for import/read operations. There is no database fallback. Validation requires original downloaded bytes in the bundle directory, or an explicit `--source-dir`.

```sh
uv run investor-financial validate research/company/annual-bundle-FY2025.json
uv run investor-financial import research/company/annual-bundle-FY2025.json --schema investor_financial_pilot --reviewed
uv run investor-financial show sec-cik:0000000001 2025 --schema investor_financial_pilot
```

Import requires an explicit `investor_financial_<name>` namespace. A fresh namespace receives the bounded versioned schema; an existing namespace must have the exact supported financial schema marker. Legacy and unrecognized namespaces are refused. The pilot bootstrap is separate from automatic portfolio migrations; it does not deploy or migrate the existing `investor_data` store.

Without `--reviewed`, imports remain candidates. The flag records the caller's completed independent review of financial facts, units, scopes, class rights and locators. Schema validity and matching document hashes establish structural integrity and saved evidence, not financial truth. In particular, a single-class denominator still needs review that it represents the relevant issuer cash-flow scope; this cannot be established from its class name alone.

Publications, observations, document versions, publication-source links and metric definitions are append-only. An identical UUID/content/review-status replay returns unchanged; a conflicting replay is refused. Corrections use a new bundle UUID. Reads select one coherent latest reviewed import, ordered by `imported_at`, per issuer and period ending in the requested calendar year, or the latest candidate import if no reviewed import exists. This does not discover the latest restatement. An older filing imported later can supersede a newer filing, so the reviewer must deliberately choose publication/import order. Each result exposes its review status, observation/source IDs, formula version and exact calculation inputs. Decimal values remain plain decimal strings; divisions use 38 significant digits. The source and period metadata are checked on reuse rather than silently replaced.

A normal annual duration must be 350–380 days for this pilot. Fiscal labels remain independent of the calendar year in which the period ends. Missing PP&E cash spending withholds FCF; optional intangible cash spending does not enter the expressly limited PP&E formula. Insurer gross margin is withheld; insurer cash-flow comparison remains the report's separate applicability decision. Source byte checks do not infer a zero from a missing line.

The read-only app endpoint is `GET /api/financials?year=2025`, supporting 2023–2025. Set `INVESTOR_FINANCIAL_SCHEMA` explicitly to the reviewed pilot namespace on the app's existing `DATABASE_URL` service, then restart the API. Requests use a consistent read-only transaction; they never create a namespace or import data. Unconfigured, missing or unsupported financial namespaces return an unavailable view. Connection or read-permission failures return a recoverable 503 without connection details.

The app uses a single declared illustrative equity-weight registry in `financial_api.py`. Its nominal USD values exercise the weighting formula; they are not actual portfolio positions or historical quotes. Responses retain the existing company/report evidence shapes and expose `synthetic`, `api_status`, coverage and availability reasons. Existing app authentication and origin checks apply.

## Disclosed cash capital spending in storage v2

An optional top-level `capital_spending` object extends the existing `schema_version: "1.0"` bundle without changing reported statement facts. It has a fixed scope, a nonempty `review_note` and a `components` object. The scope is **separately disclosed cash capital spending excluding acquisition rows**. Supported component keys are `ppe`, `property_equipment_software`, `technology_investment`, `equipment`, `leasehold_improvements`, `patents` and `other_capital_investments`. Each component is a reported, nonnegative, whole-USD consolidated annual cash outflow with a resolved source and exact locator.

The collector selects compatible, disjoint cash investment rows. Combined subtotals must not be counted alongside their components. Duplicate semantic keys, source locators and source-tag aliases are refused. The annual period is inherited from the bundle; acceptance still requires an independent check of each source's issuer, annual context, cash classification and scope. This object does not claim a sum is reported or silently split hardware/software spending.

Storage v2 adds one optional JSONB column to immutable publications. Component references use the publication UUID plus `/capital_spending/components/<key>`. New calculations retain every selected component's reference, decimal value, source and locator, plus the scope/review note. `fcf_after_disclosed_capex` subtracts their deterministic sum from reported CFO; `fcf_margin_after_disclosed_capex` divides that result by positive reported revenue. Without accepted components these results remain unavailable. Weighted ratios independently recompute the sum and verify the pinned component evidence.

The old PP&E-only inputs and formulas remain unchanged for archival use. Storage uses the `annual-financial-v2` marker and company formulas use `annual-financial-formulas-v2`. Import revised bundles with new UUIDs into a fresh explicitly configured namespace. Existing v1 namespaces are refused; neither import nor GET requests migrate or mutate them.

Coverage measures availability of this stated formula, not completeness of all investment. In particular, a mixed acquisitions/intangible-assets cash row is excluded when its acquisition-free portion cannot be identified; it is not assumed zero. Source details retain that limit. The measure is not owner earnings or estimated maintenance capital expenditure.

## References

### Project contracts

- [ADR 0008](decisions/0008-store-annual-financial-observations.md) — proposed store and immutable-observation decision.
- [Backend models](../backend/src/investor_platform/models.py) — existing securities, ledger and decimal storage.
- [ADR 0003](decisions/0003-independent-holdings.md) — independent holdings valuation and missing-price handling.
- [JSON Schema](../backend/src/investor_platform/annual_financial_bundle.schema.json) — machine-readable input structure.

### SEC filings

- [Oscar 2025 10-K](https://www.sec.gov/Archives/edgar/data/1568651/000156865126000011/oscr-20251231.htm) — insurer revenue and MLR definitions; no pilot financial figures are asserted here.
