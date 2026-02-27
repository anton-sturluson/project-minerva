# Report Format Reference

This defines the exact structure of an institutional holdings analysis report. See `hard-disk/druckenmiller-13f/analysis.md` for a live example.

## Header Block

```markdown
# {Fund Manager Name} {Quarter} 13-F Analysis
**Filed:** {filing date} | **Period:** {period end date}
**Fund:** {Fund Name} | **CIK:** {CIK number}
**Total Portfolio:** ${value} ({change% from previous quarter})
**Positions:** {count} | **Turnover:** {turnover%}
```

Turnover = (positions exited + new positions) ÷ total positions from both quarters.

---

## Top 10 Holdings

```markdown
| # | Ticker | Company | Weight | Value | Change |
|---|--------|---------|--------|-------|--------|
| 1 | NTRA | Natera | 12.8% | $575M | -22% shares trimmed |
```

- **Weight**: Position value ÷ total portfolio value
- **Value**: Round to nearest $M
- **Change**: Share change from previous quarter. Use "NEW" for new positions, "+X% added" or "-X% trimmed" for changes

---

## New Positions

```markdown
| Ticker | Company | Weight | Value | Entry Price* | Thesis |
|--------|---------|--------|-------|-------------|--------|
| XLF | Financial Sector ETF | 6.70% | $301M | $54.77 | Broad financial sector bet |
```

- **Entry Price**: Quarter-end market price (13F snapshot). Add footnote: *"Entry Price = {date} market price (13F end-of-quarter snapshot). Actual purchase price during the quarter is unknown."*
- **Thesis**: One-line investment thesis — be specific (not just "tech" but "Semiconductor materials / CHIPS Act beneficiary")
- Sort by weight descending

---

## Fully Exited Positions

This is the "scorecard" — sorted by estimated P&L, winners first.

```markdown
| Ticker | Company | Q3 Wt | Shares | Entry (Q3)* | Est. Exit* | Est. P&L | Hold |
|--------|---------|--------|--------|------------|-----------|----------|------|
| TWLO | Twilio | 1.26% | 512,800 | $100.09 | $142.24 | **+$21.6M** | 1Q |
```

- **Q3 Wt**: Weight in the previous quarter's portfolio
- **Entry**: Previous quarter's implied price (market value ÷ shares from prior 13F)
- **Est. Exit**: Current quarter-end closing price
- **Est. P&L**: (Exit - Entry) × shares. Bold positive values with `**+$X.XM**`, negative with `**-$X.XM**`
- **Hold**: "1Q" = held ~1 quarter, "2Q+" = held 2+ quarters
- End with a totals row: `| | | | | | **Net Est. P&L** | **~+$XXM** | |`

Footnotes (always include):
1. Entry/exit price methodology caveat
2. Special cases (acquisitions, delistings, options positions)
3. Hold period definition

---

## Major Increases / Decreases

Two separate tables:

```markdown
| Ticker | Company | Share Change | Notes |
|--------|---------|-------------|-------|
| GOOGL | Alphabet | +282,800 (+277%) | Massive conviction add |
```

- Include positions with >50% share change or >$20M in value change
- **Notes**: Brief context (1-5 words)

---

## Overall Fund Assessment

The centerpiece of the report. Structure:

### Opening Summary

A blockquote summarizing the quarter's activity:

```markdown
> **Summary:** {turnover}% portfolio turnover — {characterization}. {Fund manager} liquidated {X} positions
> and initiated {Y} new ones, rotating from {what} into {what}. Estimated net P&L on exits: **~+${X}M**.
>
> **The directional bet:** {theme1} > {theme2}, {theme3} > {theme4}, ...
```

### Categorized Trade Themes

Label each theme A, B, C, etc. Each follows this structure:

```markdown
### {Letter}. "{Theme Name}" — {Subtitle}

**What they did:** {Specific positions, dollar amounts, share changes}

**Why:** {Reverse-engineered macro reasoning. Be specific — cite valuations, economic data, policy shifts}

**In their own words:**
- *"{Direct quote}"* — {Date}, {Source}
- *"{Direct quote}"* — {Date}, {Source}

**Context:** {Who else is making similar moves, analyst consensus, relevant market data}
```

Guidelines for themes:
- Group related moves together (e.g., all airline buys = one theme, all bank exits = one theme)
- Each theme should tell a coherent story — what → why → evidence
- Quotes are essential — they're what distinguish this from generic portfolio analysis
- If no quotes exist for a theme, explain the reasoning from market context alone
- Typically 5-10 themes per quarter depending on activity level

### Assessment Summary Table

```markdown
| Metric | Value |
|--------|-------|
| Portfolio size | $X.XXB (+X.X% QoQ) |
| Turnover rate | XX% |
| Positions exited | XX |
| New positions | XX |
| Est. net P&L on exits | ~+$XXM |
| Largest new allocation | {Ticker} ($XXXM, X.X%) |
| Largest remaining hold | {Ticker} ($XXXM, X.X%) |
```

### Overarching Worldview

A closing paragraph synthesizing the fund's macro positioning into a coherent thesis. End with a representative quote from the fund manager.

---

## References

Follow the project citation standard in CLAUDE.md. At minimum, include:

```markdown
## References

### SEC Filings
- [Filing index]({URL}) — 13-F filing overview
- [Information table XML]({URL}) — raw holdings data

### News & Transcripts
- [{Source title}]({URL}) — {what was sourced, e.g., fund manager quotes, macro context}
```

Include any additional sources used for trade theme analysis, fund manager quotes, or market context.
