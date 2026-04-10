---
name: analyze-business
description: "Build analysis context from collected evidence and use the workflow outputs to produce a business-quality company analysis."
---

# Analyze Business

Run business analysis only after the evidence tree is materially complete. The analysis workflow packages extracted evidence into bounded section bundles that can be used with the generic `extract` command or manual writing.

## Prerequisites

- `minerva evidence coverage --root <path> --profile default` should report `ready_for_analysis: true`.
- `data/structured/` should already contain extraction outputs for the relevant markdown sources.

## Workflow

1. Check status:
   `minerva analysis status --root <path>`
2. Build section bundles:
   `minerva analysis context --root <path> --profile default`
3. Review `analysis/context-manifest.md` to confirm bundle composition and size.
4. Run focused analysis against a bundle:
   `minerva extract "<question>" --file <bundle-path> --model <model>`
5. Repeat by section, then synthesize the final note under `notes/`.

## Section Bundles

- `business-overview`: annual filings, quarterly filings, external research
- `competition`: annual filings and external research
- `management`: annual filings and earnings materials
- `risks`: annual filings, quarterly filings, external research
- `valuation`: structured financial statements, earnings materials, and any valuation markdown in `analysis/valuation/`

## Recommended Analysis Questions

- Business overview: What does the company sell, who pays, and which segments drive revenue and margin?
- Competition: Where is the moat real versus management framing, and what evidence contradicts it?
- Management: What capital allocation, operating priorities, and tone changes matter most?
- Risks: Which risks are recurring boilerplate versus newly material?
- Valuation: What do the financial statements and earnings trajectory imply about growth durability and capital intensity?

## Writing The Deep-Dive Note

- Save durable writeups under `notes/`.
- Use an explicit date and version in the filename, for example `2026-04-09-robinhood-deep-dive-v1.md`.
- Keep report-specific downloads and ad hoc research under that company root so the evidence package stays self-contained.
