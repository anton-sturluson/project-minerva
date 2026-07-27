# Sol news E2E summarizer and dry-run brief writer

You are the sole synthesis agent in an isolated end-to-end test.

- Scratch database: `{{DB}}`
- Brief artifact: `{{BRIEF}}`
- Run date: `{{DATE}}`
- Focus symbol: `{{SYMBOL}}`
- Market index: `{{INDEX}}`

Work only with the scratch DB and brief path above. Never open or modify the
canonical `invest.db` or any other database. Do not invoke Slack, webhooks, or
any messaging/posting command; this run is artifact-only.

1. Read rows from `news` whose `summary IS NULL OR trim(summary) = ''`, ordered
   deterministically by `published_at, article_key`.
2. For every such row, pass the row's normalized article `content` to the
   general command below through stdin (one invocation per row). Do not write
   temporary article files:

   ```bash
   cd {{ROOT_Q}} && printf '%s' "$content" | {{MINERVA}} summarize --model {{SUMMARY_MODEL_Q}}
   ```

3. Treat an empty summary or non-zero summarizer exit as a hard failure. Keep
   generated summaries in memory until all calls succeed. Then use Python's
   `sqlite3` parameter binding in one `BEGIN IMMEDIATE` transaction to persist
   them. Update by exact `article_key` and include
   `AND (summary IS NULL OR trim(summary) = '')`; verify each expected row was
   updated, commit only after every update succeeds, and roll back on error.
   Never interpolate article text or summaries into SQL.
4. Re-read the summarized news plus the `prices` rows for `{{SYMBOL}}` and
   `{{INDEX}}`. Write a concise investor-oriented Markdown brief directly to
   `{{BRIEF}}`. Include a heading, the important news, and both close-to-close
   market moves (current, previous close, and change percent). The brief must
   be non-empty and must clearly say `Dry run — not posted to Slack`.
5. Verify in read-only mode that no news row has a NULL/blank summary and the
   brief is non-empty. Exit non-zero if either check fails.

Do not merely describe these steps: execute them. The only allowed persistent
changes are parameterized summary updates in `{{DB}}` and the brief artifact at
`{{BRIEF}}`.
