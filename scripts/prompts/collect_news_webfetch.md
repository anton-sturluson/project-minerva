Collect and directly ingest qualifying items from {{SOURCE_NAME}} ({{URL}}) for {{DATE}} using web_fetch only.

Your isolated metadata root is `{{SOURCE_ROOT}}`. You may write only the candidate and lookup JSON files rendered below. Do not write article, Markdown, text, HTML, summary, or intermediate JSON files. Item bodies must exist only in process memory and in SQLite after a successful direct ingest.

## Portfolio context

Prioritize items relevant to these current holdings/watchlist companies:

{{PORTFOLIO_TICKERS}}

## Source-specific scope

{{COLLECT_SCOPE}}

## Selection constraints

- Collect material investor evidence relevant to the source-specific scope.
- Ingest only items published from the previous calendar date at 04:00 America/New_York inclusive through `{{DATE}}` at 04:00 America/New_York exclusive.
- When no date is visible on the landing page, retain the item only long enough to inspect its distinct destination; skip it if no publication value can be established.
- Check deterministic database duplicates before fetching distinct item pages or extracting their full bodies. Never estimate title similarity or calculate article hashes yourself.
- If no unseen qualifying items exist, ingest nothing and report zero. Do not create placeholders.
- Use web_fetch only. Never open a browser, invoke Slack/webhooks, spawn another agent, or run a summarizer. Leave `summary` absent for Charlie.

## Deterministic duplicate lookup

Write candidate metadata only as one JSON array to `{{CANDIDATE_FILE}}`, overwriting it on every lookup. Every object must contain `title`, `url`, and `published`. Use the exact distinct item URL when present; use an empty URL instead of the shared landing URL when no distinct destination exists. If a URL exists but no date is visible, use an empty `published` value for URL-first matching. Skip items with neither a destination URL nor a publication value.

Run exactly this lookup and overwrite your isolated result file:

```bash
{{NEWS_EXIST_COMMAND}} --db "{{INVEST_DB}}" --source-id "{{SOURCE_ID}}" --input "{{CANDIDATE_FILE}}" > "{{LOOKUP_FILE}}"
```

Indexes in `seen` are duplicates. Only `unseen` indexes may be collected. This read-only command uses the same normalized identity as ingestion. Run one batch lookup for all landing-page candidates.

## Direct ingest contract

For each collected item, construct exactly one in-memory JSON object with:

- `title`: exact, non-empty item title
- `source_id`: exactly `{{SOURCE_ID}}`
- `url`: the distinct item URL, or `{{URL}}` for an item that genuinely has no distinct destination
- `published_at`: the most precise visible publication value including timezone; skip the item if none exists
- `content`: normalized non-empty Markdown/plain text containing the complete substantive item, excluding navigation, advertisements, cookie text, and page chrome; never raw HTML
- optional `section`: source category
- optional `collected_at`: current ISO-8601 UTC timestamp

Pipe that single object directly on stdin to:

```bash
printf '%s\n' "$article_json" | {{NEWS_INGEST_COMMAND}}
```

A different safe in-memory JSON-producing construct is allowed, but it must end in the same `news ingest --input - --db ...` command. Never place content on a command line. Confirm the result status is `inserted`, `updated`, or `duplicate`; otherwise treat the item as failed and return non-zero.

## Steps

1. Fetch `{{URL}}` with web_fetch.
2. Identify qualifying candidates and record exact title, distinct destination URL (if any), and visible publication value without extracting distinct item bodies.
3. Apply the date rules, overwrite `{{CANDIDATE_FILE}}`, run the batch duplicate lookup, read `{{LOOKUP_FILE}}`, and retain only `unseen` indexes.
4. For each unseen item:
   a. If it has a distinct URL, fetch that URL before extracting content. If the fetch fails, skip it. A calendar row without a distinct URL may use substantive content from the landing-page fetch.
   b. Extract and normalize the full substantive item.
   c. Build one JSON object in memory and pipe it directly to the ingest command. Never write the object or body to disk.
5. If the initial fetch fails or the collector cannot complete safely, return non-zero. Do not create an error article.
6. Reply briefly with counts for inserted/updated/duplicate/skipped/failed. Do not include item bodies in your reply.

Prefer machine-readable publication metadata over rendered text and preserve exact timezone/offset information. If only a date is present, do not invent a time. No additional browser windows or tabs are allowed because this task uses web_fetch only.
