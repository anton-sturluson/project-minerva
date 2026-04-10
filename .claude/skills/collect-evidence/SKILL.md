---
name: collect-evidence
description: "Collect, register, extract, and assess company evidence with the workflow CLI before business analysis."
---

# Collect Evidence

Collect and structure company evidence for investment analysis. This workflow is deterministic and file-backed: every step writes durable artifacts under a company root.

## Workflow

1. Initialize the company tree:
   `minerva evidence init --root <path> --ticker <TICKER> --name "<Name>" --slug <slug>`
2. Collect SEC sources:
   `minerva evidence collect sec --root <path> --ticker <TICKER> --annual 5 --quarters 4 --earnings 4 --financials --html`
3. Register external sources:
   `minerva evidence register --root <path> --status downloaded --bucket external-research --source-kind <kind> --title "<title>" --path <file>`
4. Refresh inventory:
   `minerva evidence inventory --root <path>`
5. Run extraction:
   `minerva evidence extract --root <path> --profile default`
6. Check coverage:
   `minerva evidence coverage --root <path> --profile default`

## On-Disk Layout

```text
reports/00-companies/{nn}-{slug}/
  notes/
  data/
    sources/
      10-K/
      10-Q/
      earnings/
      financials/
    references/
    structured/
      10-K/
      10-Q/
      earnings/
      financials/
      references/
      registered/
    meta/
      source-registry.json
      source-registry.md
      inventory.json
      inventory.md
      coverage.json
      coverage.md
      sec-collection-summary.json
      sec-collection-summary.md
      extraction-runs/
  research/
  analysis/
    bundles/
  provenance/
```

## SEC Output Expectations

- `10-K/` and `10-Q/` contain `{date}.md` for extraction and `{date}.html` for human review.
- `earnings/` markdown should contain Exhibit `EX-99.1` when available, with `{date}.html` saved alongside it.
- `financials/` contains `income`, `balance`, and `cash` as both `.md` and `.csv`.

## Buckets And Source Kinds

- `sec-filings-annual`: `sec-10k`, `sec-10k-html`
- `sec-filings-quarterly`: `sec-10q`, `sec-10q-html`
- `sec-earnings`: `sec-8k-earnings`, `sec-8k-earnings-html`
- `sec-financial-statements`: `sec-financials-income`, `sec-financials-balance`, `sec-financials-cash`, plus `-csv` variants
- `external-research`: manually registered third-party material

## Extraction Notes

- Only markdown SEC filings, markdown financials, and registered external research are included in the default extraction profile.
- HTML files are registered for traceability and human review but are intentionally excluded from extraction.
- CSV financials are for quantitative follow-on work; they are also excluded from the default extraction profile.

## Coverage Targets

- `sec-filings-annual`: 3
- `sec-filings-quarterly`: 4
- `sec-earnings`: 4
- `sec-financial-statements`: 3
- `external-research`: 1

## When Coverage Is Not Met

1. Run `minerva evidence coverage --root <path> --profile default`.
2. Inspect `data/meta/coverage.md` and `data/meta/inventory.md` to find the missing bucket.
3. Add more downloaded or discovered sources with `minerva evidence register`.
4. Re-run `inventory`, `extract`, and `coverage` after new material is added.
