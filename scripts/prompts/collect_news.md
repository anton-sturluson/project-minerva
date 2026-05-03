Collect news from {{SOURCE_NAME}} ({{URL}}) for {{DATE}}.

1. Run: `browser open "{{URL}}" --new --window`
2. Note the tab alias from the output (e.g. t7)
3. Use `browser ask`, `browser extract`, or `browser eval` to find today's headlines and articles visible on the page
4. For editorial sources (WSJ, Economist, Reuters): extract the top headlines with section, link URL, and a 1-2 sentence summary of each
5. For calendar/data sources (BLS, BEA): extract upcoming and recently released data items with dates and descriptions
6. For IR pages: look for press releases, announcements, or news items from {{DATE}} or the most recent business day
7. Run: `browser close {tab_alias}`
8. Write the results to `{{OUTPUT_PATH}}` using the exact markdown format below

If the browser bridge is not connected, write a file with Status: failed and note the error.
If the page loads but shows a paywall or login prompt, write Status: degraded and note what happened.
If no relevant articles are found for today, write Status: ok with no article sections.

## Output format

Write this exact markdown format to {{OUTPUT_PATH}}:

```
# {{SOURCE_NAME}} — {{DATE}}

Source: {{URL}}
Collected: {current ISO timestamp}
Method: browser
Status: {ok|degraded|failed}

## {Article Headline}

Section: {section if applicable} | [link]({article_url})

{1-3 sentence summary of the article content}
```

CRITICAL: Your reply should be brief — just confirm whether the file was written and how many articles were found. All content goes into the file, not your reply.
