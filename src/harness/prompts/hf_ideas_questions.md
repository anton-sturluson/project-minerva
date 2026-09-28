# Weekly featured-fund extraction

Return exactly one JSON object, optionally inside one fenced `json` block. Do not add any other JSON object. Use this schema and these exact field names:

```json
{
  "schema_version": 1,
  "company_id": "copy exactly from Authoritative identity",
  "company": "copy company as published",
  "ticker": "copy ticker as published, or empty string",
  "exchange": "copy exchange as published, or empty string",
  "entity_type": "equity or non-stock",
  "company_summary": "one compact paragraph reconciling only the featured roster funds",
  "fund_views": [
    {
      "roster_id": "copy exactly",
      "featured_fund": "copy exact featured fund name",
      "commentary_date": "date actually attached to the fund commentary, or null",
      "stance": "bull, bear, neutral, or unclear",
      "core_thesis": "2-4 concise sentences when a thesis is supported; otherwise one short honest gap sentence",
      "source_basis": "issue, full comment, public synopsis, informational, unavailable, or non-stock",
      "source_url": "the issue or validated public URL supporting this view, or null",
      "supporting_quote": "one short exact source quote, without invented words, or empty string when no thesis quote exists",
      "unresolved_reason": "empty string when adequately supported; otherwise a specific source gap"
    }
  ]
}
```

Rules:

1. Produce exactly one `fund_views` item for every featured roster entry in the file, in source order. Copy all identity, roster, and featured-fund fields exactly. Never add or drop a fund.
2. Prioritize the matching analysis in this issue for that named fund. If it is present, `source_basis` must be `issue`; do not replace its thesis or quote with another fund's archive history.
3. Public stock-page excerpts are secondary. They are partial public evidence, not proof of full-letter access. Use `public synopsis` for a named-fund thesis synopsis, `informational` for position/activity information without a real thesis, and `unavailable` if neither supports a thesis. Do not use `full comment` unless the input explicitly labels the complete comment as available.
4. The source may mention many unrelated funds. Exclude their views from `fund_views` and `company_summary`. Do not blend fund histories. If useful at all, unrelated history may only be described as unrelated in `unresolved_reason`; it must never become the featured fund's thesis.
5. Set stance from what the named fund actually says or does. Do not force a bull case. A trim, exit, criticism, mixed comment, mere mention, or missing comment must be represented accurately as bear, neutral, or unclear as supported.
6. In `core_thesis`, capture the most important mechanism and evidence, plus valuation and risk only when cited. Do not invent a missing mechanism, number, valuation, catalyst, or risk. A public one-line synopsis cannot support details beyond that synopsis.
7. `commentary_date` is the date attached to the named commentary, not the newsletter publication date and not another fund's newer date. Use null when it is not stated.
8. The supporting quote must be copied exactly from this input and kept short. Use an empty string if no substantive quote supports the named view.
9. For an unresolved equity source, retain the entry with `stance: "unclear"`, `source_basis: "unavailable"`, and a specific short gap explanation. For the explicitly labeled non-stock item, use `entity_type: "non-stock"`, `stance: "unclear"`, and `source_basis: "non-stock"`; do not invent an equity or ticker.
10. Keep `company_summary` to one compact paragraph. Reconcile multiple featured funds explicitly if their views differ. For one fund, summarize only that fund. For unavailable/non-stock entries, write an honest one-sentence gap rather than leaving it blank.
