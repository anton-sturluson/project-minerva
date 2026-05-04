Collect data from {{SOURCE_NAME}} ({{URL}}) for {{DATE}}.

Save each item as a separate markdown file in `{{NEWS_DIR}}/raw/`.

## Steps

1. Fetch {{URL}} with the web_fetch tool
2. Identify relevant items: data releases, calendar entries, press statements, policy announcements
3. For each item with enough substance to save:
   a. Generate a short slug (lowercase, hyphens, 3-5 words)
   b. Write to `{{NEWS_DIR}}/raw/{{SOURCE_ID}}-{slug}.md` using the format below
4. If the fetch fails or returns no useful content, write one file `{{NEWS_DIR}}/raw/{{SOURCE_ID}}-error.md` with Status: failed
5. Reply briefly: how many items saved

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
