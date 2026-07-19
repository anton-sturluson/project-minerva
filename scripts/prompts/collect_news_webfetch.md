Collect data from {{SOURCE_NAME}} ({{URL}}) for {{DATE}}.

Save each item as a separate markdown file in `{{NEWS_DIR}}/raw/`.

## Portfolio context

Our current holdings and watchlist tickers (prioritize items mentioning these):

{{PORTFOLIO_TICKERS}}

## Source-specific scope

{{COLLECT_SCOPE}}

## Constraints

- **Maximum 10 items.** If the page has more, select the most relevant for a long-only investor.
- **Skip items older than 3 days** based on the visible date.
- **Calendar pages:** collect only releases dated from 3 days before {{DATE}} through 7 days after {{DATE}}. Never collect later future entries merely because they appear on the schedule. Collect no more than 5 calendar items.
- **Skip duplicates.** If an item's title or URL matches an item in the recent-items list below, do not re-collect it.
- If the fetch succeeds but no items qualify, save no files and report that zero items qualified. Do not create a placeholder or `no new releases` article.

## Recent items already collected

{{DEDUP_SLUGS}}

## Steps

1. Fetch {{URL}} with the web_fetch tool.
2. Identify relevant items: data releases, calendar entries, press statements, policy announcements.
3. Select up to 10 items, skipping any that match the dedup list or are older than 3 days.
4. For each selected item:
   a. Generate a short slug (lowercase, hyphens, 3-5 words).
   b. Write to `{{NEWS_DIR}}/raw/{{SOURCE_ID}}-{slug}.md` using the format below.
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
