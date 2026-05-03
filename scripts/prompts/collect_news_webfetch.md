Collect news from {{SOURCE_NAME}} ({{URL}}) for {{DATE}}.

1. Fetch {{URL}} with the web_fetch tool
2. Extract relevant items: releases, calendar entries, press statements, or policy announcements
3. Write the results to `{{OUTPUT_PATH}}` using the exact markdown format below

If the fetch fails or returns no useful content, write a file with Status: degraded and note the error.
If no relevant items are found for today, write Status: ok with no article sections.

## Output format

Write this exact markdown format to {{OUTPUT_PATH}}:

```
# {{SOURCE_NAME}} — {{DATE}}

Source: {{URL}}
Collected: {current ISO timestamp}
Method: web_fetch
Status: {ok|degraded|failed}

## {Item Title or Release Name}

[link]({url_if_available})

{Brief description of the item}
```

CRITICAL: Your reply should be brief — just confirm whether the file was written and how many items were found. All content goes into the file, not your reply.
