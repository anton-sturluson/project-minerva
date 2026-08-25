Collect and directly ingest news articles from {{SOURCE_NAME}} ({{URL}}) for {{DATE}}.

Your isolated metadata root is `{{SOURCE_ROOT}}`. You may write only `{{CANDIDATE_FILE}}` and `{{LOOKUP_FILE}}`, overwriting them for each lookup. Article bodies must remain in process memory until successful SQLite ingestion; never write article, Markdown, text, HTML, summary, or intermediate JSON files.

## Portfolio context

Prioritize articles relevant to these current holdings/watchlist companies:

{{PORTFOLIO_TICKERS}}

## Source-specific scope

{{COLLECT_SCOPE}}

## Eligibility and safety

- Collect every qualifying article found during the browser procedure. Rank direct portfolio relevance first, then material macro/market news, industry developments, market-relevant geopolitics/politics, and genuinely important business, technology, science, or world news. Exclude lifestyle, sports, entertainment, and celebrity stories.
- The publication window is the previous calendar date at 04:00 America/New_York inclusive through `{{DATE}}` at 04:00 America/New_York exclusive.
- A publication value is mandatory. Prefer machine-readable source metadata such as `article:published_time` or `<time datetime>` over rendered text, and preserve its exact timezone/offset. A date alone is acceptable without an invented time or timezone. When the landing page has no date, inspect article metadata before body extraction; discard the article if no publication value exists.
- Use the deterministic database lookup before expensive body extraction. Never estimate title similarity or calculate article hashes yourself.
- If no unseen eligible articles exist, ingest nothing and report zero; never create placeholders or error articles.
- Never invoke Slack, a webhook, another agent, or a summarizer. Leave `summary` absent for the synthesis step.

## Deterministic duplicate lookup

Write candidate metadata as one JSON array to `{{CANDIDATE_FILE}}`. Every object must contain `title`, `url`, and `published`; use the exact destination URL and visible publication value, or an empty `published` string when the landing page shows none.

Run this command and overwrite the lookup result:

```bash
{{NEWS_EXIST_COMMAND}} --db "{{INVEST_DB}}" --source-id "{{SOURCE_ID}}" --input "{{CANDIDATE_FILE}}" > "{{LOOKUP_FILE}}"
```

Indexes in `seen` are duplicates; only `unseen` indexes may proceed. The command is read-only and uses the same normalized identity as ingestion. Submit all landing-page candidates in one lookup. For a candidate whose date is discovered on its article page, repeat the lookup once with a one-item array containing the final URL and discovered publication value before extracting its body.

## Direct ingest contract

For each eligible unseen article, construct one in-memory JSON object with:

- `title`: exact, non-empty article headline
- `source_id`: exactly `{{SOURCE_ID}}`
- `url`: final, non-empty article URL
- `published_at`: the most precise source publication value available
- `content`: normalized non-empty Markdown or plain text containing the complete substantive article body, with navigation, advertisements, cookie text, and page chrome removed; never raw HTML
- optional `section`: source section/category
- optional `collected_at`: current ISO-8601 UTC timestamp

Pipe that object directly on stdin to:

```bash
printf '%s\n' "$article_json" | {{NEWS_INGEST_COMMAND}}
```

A different safe in-memory JSON-producing construct is allowed, but it must end in the same `news ingest --input - --db ...` command. Never place article JSON or content on a command line. Require the compact command result to have status `inserted`, `updated`, or `duplicate`; otherwise count the article as failed and report collector status `failed` after continuing safely.

## Browser lease procedure

Your assigned browser alias is exactly `{{BROWSER_ALIAS}}`. Use only this lease-checked command prefix for browser work:

```bash
{{LEASED_BROWSER_COMMAND}}
```

Every browser operation must use that prefix, which deterministically targets only the assigned alias. Never invoke the raw browser CLI/tool, enumerate or focus tabs, create a tab or window, supply a tab-selection or new-window option, or close the lease. The deterministic runner owns cleanup.

1. Navigate the existing leased tab exactly once to the landing page: `{{LEASED_BROWSER_COMMAND}} open "{{URL}}"`.
2. In that leased tab, scan the homepage and each distinct top-level editorial section in the compact or horizontal primary navigation exactly once, including `Latest Headlines` or `World in Brief` when present. If the navigation is collapsed, open the primary menu only far enough to recover that same section list. Record candidate headline, destination URL, visible publication value, and section without opening article bodies; ignore secondary mega-menu links, subsections, topic pages, pagination, archives, search, and utility/media pages.
3. Deduplicate candidates by destination URL, remove visibly stale candidates, run the batch duplicate lookup, and retain only `unseen` indexes.
4. For each remaining candidate, use only the same leased alias to:
   a. Navigate to the article and resolve missing publication metadata as specified above.
   b. Extract and normalize the full substantive body with `{{LEASED_BROWSER_COMMAND}} extract` or `{{LEASED_BROWSER_COMMAND}} ask`.
   c. Build and ingest the in-memory object.
   d. Record an unavailable, paywalled, or video-only item as skipped and continue. Count a browser or extraction failure as failed and continue safely.
5. Leave the assigned lease open and return the final report described below.

If the browser bridge is unavailable or safe completion is impossible, report status `failed`. Additional tabs and windows are not allowed.

## Final report

Your final reply must be exactly one compact JSON object with no Markdown, preamble, or trailing text: `{"status":"ok","inserted":0,"updated":0,"duplicate":0,"skipped":0,"failed":0}`. Use only the keys shown, with `status` set to `ok` or `failed` and every count set to a nonnegative integer. `status` may be `ok` only when `failed` is zero; any browser, fetch, or safe-completion failure must use `failed`. Do not include article bodies.
