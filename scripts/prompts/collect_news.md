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

A different safe in-memory JSON-producing construct is allowed, but it must end in the same `news ingest --input - --db ...` command. Never place article JSON or content on a command line. Require the compact command result to have status `inserted`, `updated`, or `duplicate`; otherwise count the article as failed and return a non-zero result after continuing safely.

## Browser procedure

1. Run exactly once: `browser open "{{URL}}" --new --window`.
2. Record the returned tab alias. It is your only browser window and tab. Never run `browser open` again; close any accidentally created extra tab or window immediately.
3. In that tab, scan the homepage and each distinct top-level editorial section in the compact or horizontal primary navigation exactly once, including `Latest Headlines` or `World in Brief` when present. If the navigation is collapsed, open the primary menu only far enough to recover that same section list. Record candidate headline, destination URL, visible publication value, and section without opening article bodies; ignore secondary mega-menu links, subsections, topic pages, pagination, archives, search, and utility/media pages.
4. Deduplicate candidates by destination URL, remove visibly stale candidates, run the batch duplicate lookup, and retain only `unseen` indexes.
5. For each remaining candidate, use the same tab to:
   a. Navigate to the article and resolve missing publication metadata as specified above.
   b. Extract and normalize the full substantive body with `browser extract` or `browser ask`.
   c. Build and ingest the in-memory object.
   d. On 404, CAPTCHA, video-only content, paywall, or extraction failure, record a skipped item and continue.
6. Close the tab with `browser close {tab_alias}`.
7. Reply briefly with counts for inserted/updated/duplicate/skipped/failed. Do not include article bodies.

If the browser bridge is unavailable or safe completion is impossible, return non-zero. Same-tab navigation is allowed; additional tabs and windows are not.
