Collect news articles from {{SOURCE_NAME}} ({{URL}}) for {{DATE}}.

Save each article as a separate markdown file in `{{NEWS_DIR}}/raw/`.
Your isolated source root is `{{NEWS_DIR}}`. Only write within this rendered root.

## Portfolio context

Our current holdings and watchlist tickers (prioritize articles mentioning these):

{{PORTFOLIO_TICKERS}}

## Source-specific scope

{{COLLECT_SCOPE}}

## Constraints

- **Source ownership:** never list, read, count, rename, modify, or delete another source's files. Do not inspect parent or sibling directories. For collector working files, use only this source's `raw/`, `candidates/`, and `lookups/` directories under `{{NEWS_DIR}}`, and every file you write must stay within `{{NEWS_DIR}}`.
- Scan the full landing page and collect every qualifying relevant article. Prioritize: (1) direct relevance to portfolio companies above, (2) macro/market significance, (3) industry trends, (4) geopolitics or politics that affects the economy or markets, (5) genuinely interesting business, technology, science, or world stories a thoughtful investor would want to know. Skip lifestyle, sports, entertainment, and celebrity fluff.
- **Skip articles older than 3 days** based on the visible publish date. If no date is visible, keep the article as a candidate for the URL-first check below.
- **Skip database duplicates before opening an article.** Use the deterministic batch lookup below; do not estimate title similarity or calculate article hashes yourself.
- If no qualifying new articles exist, save no files and report that zero items qualified. Do not create a placeholder article.

## Deterministic database lookup

Write all candidates as one JSON array to `{{CANDIDATE_FILE}}`, overwriting that file on every lookup. Each object must contain `title`, `url`, and `published`. Use the exact destination URL and visible publication value. If no date is visible on the landing page, use an empty `published` string so the command checks the URL first.

Run the lookup below and redirect its compact JSON result to the collector's own lookup file, also overwriting it:

```bash
{{NEWS_EXIST_COMMAND}} --db "{{INVEST_DB}}" --source-id "{{SOURCE_ID}}" --input "{{CANDIDATE_FILE}}" > "{{LOOKUP_FILE}}"
```

Candidate indexes in `seen` are duplicates; only indexes in `unseen` may be visited. The command opens SQLite read-only and applies the same publication-date normalization and article identity code used during ingestion. Run one batch check for the landing page, not one command per candidate.

## Steps

1. Run exactly once: `browser open "{{URL}}" --new --window`
2. Note the tab alias from the output (e.g. t7). This is your only browser window and tab for the entire task. Do not run `browser open` again, create another window, or open article links in new tabs.
3. In that one existing tab, scan the full landing page. Identify all potentially relevant articles and record each exact headline, destination URL, and visible publication date without opening any article.
4. Remove candidates whose visible date is older than 3 days. Overwrite `{{CANDIDATE_FILE}}` with every remaining candidate, run the lookup command, read `{{LOOKUP_FILE}}`, then remove every index classified as `seen`.
5. For each `unseen` article:
   a. Navigate the existing tab into the article. Never open a new tab or window.
   b. If its publication date was unavailable on the landing page, inspect the article's date or machine-readable metadata without extracting the full body. Before body extraction, overwrite `{{CANDIDATE_FILE}}` with a one-item array containing that date and the final article URL, rerun the same lookup command so `{{LOOKUP_FILE}}` is overwritten, and read the result. If the article still exposes no date, use `{{DATE}}`, matching ingestion's collection-date fallback. If it is now `seen`, navigate back and skip it.
   c. Extract the full article text using `browser extract` or `browser ask`.
   d. Generate a short slug from the headline (lowercase, hyphens, 3-5 words, e.g. `trump-hormuz-ships`).
   e. Write the full article to `{{NEWS_DIR}}/raw/{{SOURCE_ID}}-{slug}.md` using the format below.
   f. Navigate the same tab back to the landing page.
   g. If extraction fails (404, CAPTCHA, video-only, paywall prompt), skip the article and continue to the next one.
6. After all articles are saved, close your only browser tab: `browser close {tab_alias}`. If an extra tab or window was created accidentally, close it immediately before continuing.
7. Reply briefly: how many articles saved, any skipped (with reason), any failures.

If the browser bridge is not connected, write one file `{{NEWS_DIR}}/raw/{{SOURCE_ID}}-error.md` with Status: failed.
If the page shows a paywall or login prompt, note it and continue with what's accessible.

## File format for each article

Write this exact format to `{{NEWS_DIR}}/raw/{{SOURCE_ID}}-{slug}.md`:

```
# {Article Headline}

Source: {{SOURCE_NAME}}
URL: {article_url}
Published: {most precise publication datetime + timezone visible on the article}
Collected: {current ISO timestamp}
Section: {section if applicable}

{Full article text — the complete body of the article as visible on the page}
```

### Recording the Published value

- Copy the most precise publication timestamp visible on the article page or its HTML metadata (`<meta property="article:published_time">`, `<time datetime="...">`, byline dateline, etc.). Prefer machine-readable page metadata over rendered text when both are present.
- Include the timezone or UTC offset exactly as shown (e.g. `2026-07-16T09:00:00-04:00`, `July 16, 2026 9:00 AM EDT`, `Jul 16th 2026`).
- If only a date is visible (no time), record just the date. Never invent, round, or fill in a time that is not shown on the page.
- If no publication date is visible anywhere on the page, use `{{DATE}}` (the run date) as a last resort and flag that in your reply.

## Important

- One file per article. Do NOT combine articles into one file.
- Save the FULL article text, not a summary.
- Do NOT spawn subagents. Collect all articles yourself in exactly one browser window containing exactly one tab. Same-tab navigation is allowed; no additional windows or tabs are allowed.
- If you detect slug collision (two articles would get the same filename), append a number: `{slug}-2`.
- Your reply should be brief. All content goes into the files.
