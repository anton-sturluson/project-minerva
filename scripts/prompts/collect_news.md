Collect and directly ingest news articles from {{SOURCE_NAME}} ({{URL}}) for {{DATE}}.

Your isolated metadata root is `{{SOURCE_ROOT}}`. You may write only the candidate and lookup JSON files rendered below. Do not write article, Markdown, text, HTML, summary, or intermediate JSON files. Article bodies must exist only in process memory and in SQLite after a successful direct ingest.

## Portfolio context

Prioritize articles relevant to these current holdings/watchlist companies:

{{PORTFOLIO_TICKERS}}

## Source-specific scope

{{COLLECT_SCOPE}}

## Selection constraints

- Scan the full landing page and collect every qualifying article. Rank direct portfolio relevance first, then material macro/market news, industry developments, market-relevant geopolitics/politics, and genuinely important business, technology, science, or world news. Skip lifestyle, sports, entertainment, and celebrity stories.
- Skip articles older than 3 days based on the visible source publication date. If no date is visible on the landing page, retain the item for the URL-first duplicate check.
- Check deterministic database duplicates before expensive article-body extraction. Never estimate title similarity or calculate article hashes yourself.
- If no unseen qualifying articles exist, ingest nothing and report zero. Do not create placeholders.
- Never invoke Slack, a webhook, another agent, or a summarizer. Leave `summary` absent so the outer Sol agent can summarize later.

## Deterministic duplicate lookup

Write candidate metadata only as one JSON array to `{{CANDIDATE_FILE}}`, overwriting it on every lookup. Every object must contain `title`, `url`, and `published`. Use the exact destination URL and visible publication value; use an empty `published` string when no date is visible.

Run exactly this lookup and overwrite your isolated result file:

```bash
{{NEWS_EXIST_COMMAND}} --db "{{INVEST_DB}}" --source-id "{{SOURCE_ID}}" --input "{{CANDIDATE_FILE}}" > "{{LOOKUP_FILE}}"
```

Indexes in `seen` are duplicates. Only indexes in `unseen` may be visited. This command is read-only and uses the same normalized identity as ingestion. Batch the landing-page candidates in one lookup rather than invoking it once per candidate.

## Direct ingest contract

For each extracted article, construct exactly one in-memory JSON object with:

- `title`: exact, non-empty article headline
- `source_id`: exactly `{{SOURCE_ID}}`
- `url`: final, non-empty article URL
- `published_at`: the most precise source publication value available, including timezone; use `{{DATE}}` only when the article exposes no publication date
- `content`: normalized non-empty Markdown or plain text containing the complete substantive article body, with navigation, advertisements, cookie text, and page chrome removed; never raw HTML
- optional `section`: source section/category
- optional `collected_at`: current ISO-8601 UTC timestamp

Pipe that single object directly on stdin to this command:

```bash
printf '%s\n' "$article_json" | {{NEWS_INGEST_COMMAND}}
```

A different safe in-memory JSON-producing construct is allowed, but it must end in the same `news ingest --input - --db ...` command. Never place article JSON or content on a command line. Confirm the compact command result has status `inserted`, `updated`, or `duplicate`; otherwise treat that article as failed and return a non-zero collector result.

## Browser steps

1. Run exactly once: `browser open "{{URL}}" --new --window`.
2. Record the returned tab alias. It is your only browser window and tab. Never run `browser open` again and never create another tab/window.
3. In that tab, scan the complete landing page. Record candidate headline, destination URL, and visible publication value without opening article bodies.
4. Remove visibly stale candidates. Overwrite `{{CANDIDATE_FILE}}`, run the one batch lookup, read `{{LOOKUP_FILE}}`, and keep only `unseen` indexes.
5. For each unseen candidate:
   a. Navigate the same tab to the article.
   b. If its date was unavailable on the landing page, inspect only date metadata first. Before body extraction, overwrite `{{CANDIDATE_FILE}}` with a one-item array using the final URL and discovered date (or `{{DATE}}` if no date exists), rerun the lookup, and skip the article if it is now `seen`.
   c. Extract and normalize the full substantive article body with `browser extract` or `browser ask`.
   d. Build one JSON object in memory and pipe it directly to the ingest command above. Do not write it to disk.
   e. Navigate the same tab back to the landing page.
   f. On 404, CAPTCHA, video-only content, paywall, or extraction failure, skip the article and continue.
6. Close your only tab with `browser close {tab_alias}`. Close any accidentally created extra tab/window immediately.
7. Reply briefly with counts for inserted/updated/duplicate/skipped/failed. Do not include article bodies in your reply.

## Publication value

Prefer machine-readable source metadata such as `article:published_time` or `<time datetime>` over rendered text. Preserve the exact timezone/offset shown. If only a date is available, use that date without inventing a time. Use `{{DATE}}` only as the last-resort no-date fallback and mention the fallback in your brief reply.

If the browser bridge is unavailable or the collector cannot complete safely, return non-zero. Do not create an error article or any article-body file. Same-tab navigation is allowed; additional tabs/windows are not.
