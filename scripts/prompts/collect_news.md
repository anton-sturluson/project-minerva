Collect news articles from {{SOURCE_NAME}} ({{URL}}) for {{DATE}}.

Save each article as a separate markdown file in `{{NEWS_DIR}}/raw/`.

## Portfolio context

Our current holdings and watchlist tickers (prioritize articles mentioning these):

{{PORTFOLIO_TICKERS}}

## Constraints

- **Maximum 10 articles.** Scan the full front page first, then select the top 10 (or fewer) most relevant. Prioritize by: (1) direct relevance to portfolio companies above, (2) macro/market significance, (3) industry trends, (4) geopolitics that affects markets. Skip lifestyle, sports, entertainment, and celebrity fluff.
- **Skip articles older than 3 days** based on the visible publish date. If no date is visible, include the article.
- **Skip duplicates.** If an article's slug matches any in the dedup list below, do not re-collect it.

## Dedup list (already collected recently)

{{DEDUP_SLUGS}}

## Steps

1. Run: `browser open "{{URL}}" --new --window`
2. Note the tab alias from the output (e.g. t7).
3. Scan the front page. Identify all potentially relevant articles and their headlines.
4. Select up to 10 articles, skipping any that match the dedup list or are older than 3 days.
5. For each selected article:
   a. Click into it (or open in a new tab).
   b. Extract the full article text using `browser extract` or `browser ask`.
   c. Generate a short slug from the headline (lowercase, hyphens, 3-5 words, e.g. `trump-hormuz-ships`).
   d. Write the full article to `{{NEWS_DIR}}/raw/{{SOURCE_ID}}-{slug}.md` using the format below.
   e. Navigate back to the front page (or close the tab and return to the main tab).
   f. If extraction fails (404, CAPTCHA, video-only, paywall prompt), skip the article and continue to the next one.
6. After all articles are saved, close the browser: `browser close {tab_alias}`
7. Reply briefly: how many articles saved, any skipped (with reason), any failures.

If the browser bridge is not connected, write one file `{{NEWS_DIR}}/raw/{{SOURCE_ID}}-error.md` with Status: failed.
If the page shows a paywall or login prompt, note it and continue with what's accessible.

## File format for each article

Write this exact format to `{{NEWS_DIR}}/raw/{{SOURCE_ID}}-{slug}.md`:

```
# {Article Headline}

Source: {{SOURCE_NAME}}
URL: {article_url}
Published: {date if visible, otherwise {{DATE}}}
Collected: {current ISO timestamp}
Section: {section if applicable}

{Full article text — the complete body of the article as visible on the page}
```

## Important

- One file per article. Do NOT combine articles into one file.
- Save the FULL article text, not a summary.
- Do NOT spawn subagents. Collect all articles yourself in a single browser tab.
- If you detect slug collision (two articles would get the same filename), append a number: `{slug}-2`.
- Your reply should be brief. All content goes into the files.
