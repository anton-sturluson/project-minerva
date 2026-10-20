# Debt issuance extraction pilot

This is an isolated test of public financing disclosures. It writes a validated JSON
snapshot and a standalone HTML visualization. It adds no platform database tables,
API routes, scheduled jobs or production changes.

The main cohort is Microsoft, Amazon, Alphabet, Meta, Oracle, CoreWeave, Nebius and
IREN. SPGI has a separate reported-quarter sample. Nscale, Lambda and Crusoe have
limited financing examples, with their disclosure limits shown explicitly.

## Reproduce

Run from the repository root with `EDGAR_IDENTITY` set to the configured SEC
contact header. This value is used for requests and is never written into output.
The first run downloads source files; subsequent runs replay the saved bytes.

```sh
uv run --project investor-platform/backend --frozen python investor-platform/experiments/debt-issuance/spgi.py --research-dir hard-disk/reports/debt-issuance-pilot/research/spgi --output hard-disk/reports/debt-issuance-pilot/spgi.json
uv run --project investor-platform/backend --frozen python investor-platform/experiments/debt-issuance/collect.py --output-dir hard-disk/reports/debt-issuance-pilot --events investor-platform/experiments/debt-issuance/events.json --spgi hard-disk/reports/debt-issuance-pilot/spgi.json
uv run --project investor-platform/backend --frozen python investor-platform/experiments/debt-issuance/render.py hard-disk/reports/debt-issuance-pilot/snapshot.json
uv run --project investor-platform/backend --frozen pytest investor-platform/experiments/debt-issuance
```

The event sample is explicitly reviewed data in `events.json`; it is not the
output of an exhaustive automatic bond parser. Its raw payload hashes refer to
the original retrieval. A fresh download can differ because a publisher changed
a page; retain the original evidence with this pilot's generated report.

## Research Log

### Hypothesis

Original SEC data and selected issuer disclosures can support a useful, traceable
financing view while keeping completed bonds, cash borrowing, loans, equity and
commitments separate. The test must expose missing data rather than infer zeros.

### Timeline

- 2026-10-20: Set the disclosure cutoff and company cohort. Start the clean pilot.
- 2026-10-20: Preserve original source payloads beside the local report; attach
  SHA-256 hashes and source references to extracted figures.

### Experiments

- Read SEC company facts and filing metadata for cash-flow periods starting in 2024
  or later. Reject disclosures filed after the cutoff. Retain actual reported
  quarter, cumulative year-to-date and annual periods, with their date bounds.
- Derive a discrete quarter only when compatible inputs appear in the same
  filing. Separate cumulative and annual periods in the visualization. Custom
  accounting tags and unavailable quarterly disclosures stay missing.
- Review a bounded sample of financing events completed since 2025. This is a
  cited sample, not an exhaustive scan of every issue. Preserve native currencies,
  legal issuers, convertible status, tranches and reported maturity precision.
- Extract SPGI billed issuance and Ratings revenue from two pinned quarterly
  filings. Read current and comparative quarter columns; do not substitute
  cumulative figures, percentage changes or percentage-of-revenue rows.
- Validate source references, exact amounts, tranche sums, period scope and
  cutoff dates before rendering. Test desktop and narrow layouts.

### Results

- 243 cash-flow values across 77 populated periods for the eight-company cohort.
  The 126-row period grid also retains unavailable quarter records as explicit
  gaps. Populated records comprise 29 quarterly, 18 six-month, 14 nine-month and
  16 annual periods; these overlapping durations must not be added together.
- Four SPGI quarters (Q1/Q2 of 2025 and 2026) provide 24 issuance/revenue values.
  The sample is not four consecutive quarters and does not support a trailing
  four-quarter total.
- Nine closed, currency-specific bond records cover seven companies. There are
  seven USD records and one each in EUR and GBP. Microsoft has no verified deal
  in this sample; that does not establish zero issuance. Every issuer's bond
  sample has partial coverage.
- Three other financing examples remain outside the bond chart: Lambda's term
  loan, Nscale's convertible financing with a future commitment, and Crusoe's
  equity financing announcement.
- All 46 source payload hashes were found in the retained research directory.
- Key limits: Amazon cash capex and some Oracle/IREN debt proceeds use custom
  disclosures outside the selected standard tags. Alphabet's combined debt and
  lease repayment line is excluded from pure debt repayments. Nebius has useful
  annual data but no quarterly series from the selected API/form scope.

### References

- [SEC data APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)
  — filing discovery, standard taxonomy and entity-level accounting facts.
- [SPGI Q1 2026 filing](https://www.sec.gov/Archives/edgar/data/64040/000006404026000024/spgi-20260331.htm)
  and [Q2 2026 filing](https://www.sec.gov/Archives/edgar/data/64040/000006404026000045/spgi-20260630.htm)
  — reported billed issuance and Ratings revenue, including comparative quarters.
- [Alphabet closing report](https://www.sec.gov/Archives/edgar/data/1652044/000119312526051423/d946885d8k.htm)
  — completed notes with separate currencies and maturities.
- [Nebius closed convertible notes](https://nebius.com/newsroom/nebius-group-announces-closing-of-private-offering-of-convertible-senior-notes-with-aggregate-gross-proceeds-of-approximately-5-75-billion)
  — an example of neocloud convertible financing.
- [Lambda closed term loan](https://lambda.ai/blog/lambda-closes-926-million-senior-secured-term-loan-b-facility)
  — a loan that must remain outside the bond total.

The event registry contains the remaining primary source URLs. Downloaded source
materials and generated reports belong in the ignored report directory, never in
Git. Do not store credentials, local account details or private preview links in
this experiment's public files.
