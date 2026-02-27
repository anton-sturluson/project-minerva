---
name: 13f-analysis
description: "Analyze SEC 13-F institutional holdings filings. Use when the user asks to analyze a fund manager's portfolio, compare quarterly holdings, or review 13-F filings."
---

# 13-F Institutional Holdings Analysis

## Overview
Analyze SEC 13-F filings to produce institutional-grade portfolio analysis reports with quarter-over-quarter comparisons, position tracking, and investment theme identification.

## Library Dependencies
- `minerva.sec.get_13f_comparison(cik)` — QoQ holdings diff with current/previous/new/exited/increased/decreased DataFrames
- `minerva.sec.get_10k_items(ticker, items)` — supplementary 10-K data for thesis context
- `minerva.formatting.build_markdown_table()`, `format_usd()`, `format_pct()` — output formatting
- `edgartools` directly for identity setup, company lookup, insider transactions:
  ```python
  from edgar import Company, set_identity
  set_identity("Minerva Research minerva@research.dev")
  ```

## Workflow

1. **Identify the fund**: Get CIK from user (or look up via `Company` search)
2. **Fetch 13-F comparison**: `get_13f_comparison(cik)` returns current vs previous quarter
3. **Analyze changes**: Categorize new positions, exits, increases, decreases
4. **Enrich with context**: Use web search for fund manager quotes, thesis context
5. **Generate report**: Follow the format in `references/report-format.md`

## Report Format
See [references/report-format.md](references/report-format.md) for the exact report structure including:
- Header block with fund metadata
- Top 10 holdings table
- New positions with entry prices and thesis
- Fully exited positions with estimated P&L
- Major increases/decreases
- Overall Fund Assessment with categorized trade themes

## Output
Save report to `hard-disk/reports/{fund-name}-13f/analysis.md` with all research materials in `research/` subdirectory.
