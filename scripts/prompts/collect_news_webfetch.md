Collect data from {{SOURCE_NAME}} ({{URL}}) for {{DATE}}.

Save each item as a separate markdown file in `{{NEWS_DIR}}/raw/`.

## Portfolio context

Our current holdings and watchlist tickers (prioritize items mentioning these):

{{PORTFOLIO_TICKERS}}

## Constraints

- **Maximum 10 items.** If the page has more, select the most relevant for a long-only investor.
- **Skip items older than 3 days** based on the visible date.
- **Skip duplicates.** If an item's slug matches any in the dedup list below, do not re-collect it.

## Dedup list (already collected recently)

{{DEDUP_SLUGS}}

## Steps

1. Fetch {{URL}} with the web_fetch tool.
2. Identify relevant items: data releases, calendar entries, press statements, policy announcements.
3. Select up to 10 items, skipping any that match the dedup list or are older than 3 days.
4. For each selected item:
   a. Generate a short slug (lowercase, hyphens, 3-5 words).
   b. Write to `{{NEWS_DIR}}/raw/{{SOURCE_ID}}-{slug}.md` using the format below.
5. If the fetch fails or returns no useful content, write one file `{{NEWS_DIR}}/raw/{{SOURCE_ID}}-error.md` with Status: failed.
6. Reply briefly: how many items saved, any skipped.

## File format

Write this exact format to `{{NEWS_DIR}}/raw/{{SOURCE_ID}}-{slug}.md`:

```
# {Item Title or Release Name}

Source: {{SOURCE_NAME}}
URL: {item_url_if_available}
Published: {date if visible, otherwise {{DATE}}}
Collected: {current ISO timestamp}
Section: {category if applicable}

{Full text of the release, calendar entry, or announcement}
```

## Important

- One file per item. Do NOT combine items into one file.
- Save the full content, not a summary.
- Your reply should be brief. All content goes into the files.
