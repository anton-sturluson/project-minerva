Collect and directly ingest qualifying items from {{SOURCE_NAME}} ({{URL}}) for {{DATE}} using web_fetch only.

Your isolated metadata root is `{{SOURCE_ROOT}}`. You may write only `{{CANDIDATE_FILE}}` and `{{LOOKUP_FILE}}`, overwriting them for each lookup. Item bodies must remain in process memory until successful SQLite ingestion; never write article, Markdown, text, HTML, summary, or intermediate JSON files.

## Portfolio context

Prioritize items relevant to these current holdings/watchlist companies:

{{PORTFOLIO_TICKERS}}

## Source-specific scope

{{COLLECT_SCOPE}}

## Eligibility and safety

- Collect material investor evidence relevant to the source-specific scope.
- The publication window is the previous calendar date at 04:00 America/New_York inclusive through `{{DATE}}` at 04:00 America/New_York exclusive.
- A publication value is mandatory. Prefer machine-readable metadata over rendered text and preserve its exact timezone/offset. A date alone is acceptable without an invented time or timezone. When the landing page has no date, inspect the distinct destination before body extraction; discard the item if no publication value exists.
- Use the deterministic database lookup before fetching distinct item pages or extracting full bodies. Never estimate title similarity or calculate article hashes yourself.
- If no unseen eligible items exist, ingest nothing and report zero; never create placeholders or error articles.
- Never open a browser, invoke Slack or webhooks, spawn another agent, or run a summarizer. Leave `summary` absent for the synthesis step.

## Deterministic duplicate lookup

Write candidate metadata as one JSON array to `{{CANDIDATE_FILE}}`. Every object must contain `title`, `url`, and `published`. Use the exact distinct item URL when present, or an empty URL rather than the shared landing URL when none exists. Use an empty `published` string when the landing page shows no date. An item with neither a destination URL nor a publication value is ineligible.

Run this command and overwrite the lookup result:

```bash
{{NEWS_EXIST_COMMAND}} --db "{{INVEST_DB}}" --source-id "{{SOURCE_ID}}" --input "{{CANDIDATE_FILE}}" > "{{LOOKUP_FILE}}"
```

Indexes in `seen` are duplicates; only `unseen` indexes may proceed. The command is read-only and uses the same normalized identity as ingestion. Submit all landing-page candidates in one lookup. For a candidate whose date is discovered at its destination, repeat the lookup once with a one-item array containing the final URL and discovered publication value before extracting its body.

## Direct ingest contract

For each eligible unseen item, construct one in-memory JSON object with:

- `title`: exact, non-empty item title
- `source_id`: exactly `{{SOURCE_ID}}`
- `url`: the distinct item URL, or `{{URL}}` when the item genuinely has no distinct destination
- `published_at`: the most precise source publication value available
- `content`: normalized non-empty Markdown or plain text containing the complete substantive item, excluding navigation, advertisements, cookie text, and page chrome; never raw HTML
- optional `section`: source category
- optional `collected_at`: current ISO-8601 UTC timestamp

Pipe that object directly on stdin to:

```bash
printf '%s\n' "$article_json" | {{NEWS_INGEST_COMMAND}}
```

A different safe in-memory JSON-producing construct is allowed, but it must end in the same `news ingest --input - --db ...` command. Never place content on a command line. Require the compact command result to have status `inserted`, `updated`, or `duplicate`; otherwise count the item as failed and return a non-zero result after continuing safely.

## Procedure

1. Fetch `{{URL}}` with web_fetch.
2. Identify qualifying candidates and record exact title, distinct destination URL (if any), and visible publication value without extracting distinct item bodies.
3. Apply the eligibility rules, run the batch duplicate lookup, and retain only `unseen` indexes.
4. For each remaining item:
   a. Fetch its distinct URL when one exists; a calendar row without a distinct URL may use substantive content from the landing-page fetch.
   b. Resolve missing publication metadata as specified above, then extract and normalize the complete substantive item.
   c. Build and ingest the in-memory object.
   d. Record fetch or extraction failures as skipped and continue.
5. If the initial fetch fails or safe completion is impossible, return non-zero.
6. Reply briefly with counts for inserted/updated/duplicate/skipped/failed. Do not include item bodies.
