Collect data from {{SOURCE_NAME}} ({{URL}}) for {{DATE}}.

Save each item as a separate markdown file in `{{NEWS_DIR}}/raw/`.

## Portfolio context

Our current holdings and watchlist tickers (prioritize items mentioning these):

{{PORTFOLIO_TICKERS}}

## Source-specific scope

{{COLLECT_SCOPE}}

## Constraints

- **Skip items older than 3 days** based on the visible date.
- **Calendar pages:** collect only releases dated from 3 days before {{DATE}} through 7 days after {{DATE}}. Never collect later future entries merely because they appear on the schedule.
- **Skip database duplicates.** Use the deterministic batch lookup below; do not estimate title similarity or calculate article hashes yourself.
- If the fetch succeeds but no items qualify, save no files and report that zero items qualified. Do not create a placeholder or `no new releases` article.

## Deterministic database lookup

Write all candidates as one JSON array to `{{CANDIDATE_FILE}}`, overwriting that file on every lookup. Each object must contain `title`, `url`, and `published`. Use the exact item URL and visible publication value. If an item has no distinct URL, use an empty string rather than the shared landing-page URL. If neither a distinct URL nor a date is available, use `{{DATE}}` as `published`, matching ingestion's collection-date fallback; if the URL exists but the date does not, leave `published` empty for the URL-first check.

Run the lookup below and redirect its compact JSON result to the collector's own lookup file, also overwriting it:

```bash
{{NEWS_EXIST_COMMAND}} --db "{{INVEST_DB}}" --source-id "{{SOURCE_ID}}" --input "{{CANDIDATE_FILE}}" > "{{LOOKUP_FILE}}"
```

Candidate indexes in `seen` are duplicates; only indexes in `unseen` may be collected. The command opens SQLite read-only and applies the same publication-date normalization and article identity code used during ingestion. Run one batch check for all candidates.

## Steps

1. Fetch {{URL}} with the web_fetch tool.
2. Identify relevant items: data releases, calendar entries, press statements, policy announcements. Record each exact title, destination URL, and visible publication date.
3. Exclude items outside the date rules. Overwrite `{{CANDIDATE_FILE}}` with every remaining candidate, run the lookup command, read `{{LOOKUP_FILE}}`, and retain only the `unseen` indexes.
4. For each unseen item:
   a. If it has a distinct item URL, fetch that URL with the web_fetch tool before writing anything and use the fetched item's full content. If that item fetch fails, skip it and continue. A calendar row without a distinct URL may use the already-fetched landing-page content.
   b. Generate a short slug (lowercase, hyphens, 3-5 words).
   c. Write to `{{NEWS_DIR}}/raw/{{SOURCE_ID}}-{slug}.md` using the format below.
5. If the fetch itself fails, write one file `{{NEWS_DIR}}/raw/{{SOURCE_ID}}-error.md` with Status: failed. If the fetch succeeds but no items qualify, write no file.
6. Reply briefly: how many items saved, any skipped.

## File format

Write this exact format to `{{NEWS_DIR}}/raw/{{SOURCE_ID}}-{slug}.md`:

```
# {Item Title or Release Name}

Source: {{SOURCE_NAME}}
URL: {item_url_if_available}
Published: {most precise publication datetime + timezone visible on the item}
Collected: {current ISO timestamp}
Section: {category if applicable}

{Full text of the release, calendar entry, or announcement}
```

### Recording the Published value

- Copy the most precise publication timestamp visible on the page or in its metadata (`<meta property="article:published_time">`, `<time datetime="...">`, dateline, release header). Prefer machine-readable page metadata over rendered text.
- Include the timezone or UTC offset exactly as shown (e.g. `2026-07-14T08:30:00-04:00`, `July 14, 2026 8:30 AM ET`).
- If only a date is visible (no time), record just the date. Never invent, round, or fabricate a time that is not shown.
- If no publication date is visible anywhere, use `{{DATE}}` as a last resort and flag that in your reply.

## Important

- One file per item. Do NOT combine items into one file.
- Save the full content, not a summary.
- Your reply should be brief. All content goes into the files.
