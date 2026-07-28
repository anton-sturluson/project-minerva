# Morning brief synthesis contract

The collection script has already populated prepared evidence, `news`, and `prices`. Do not repeat collection, browse the web, delegate synthesis, or post to Slack with a messaging tool.

Read the `synthesis-handoff.json` path printed by `scripts/run_morning_brief.sh`. Treat its `date`, `window_start`, `window_end`, `db`, `prepared_evidence`, `report_output`, and `slack_brief_output` values as authoritative.

## 1. Summarize pending news

- Select eligible `news` rows using `published_at` as UTC epoch seconds in the fixed half-open interval from `window_start` inclusive to `window_end` exclusive. The handoff timestamps represent the previous run date at 04:00 through the run date at 04:00 in `America/New_York`. Do not use calendar-date prefix matching or include rows outside these exact bounds.
- Process only rows where `content` is non-empty and `summary` is NULL or blank.
- For each row, pipe `content` on stdin to:

```bash
uv run minerva summarize --model gemini-3.6-flash --thinking high
```

- Use bounded parallelism of at most four subprocesses. Keep article content and generated summaries in memory; do not write article or summary files.
- If any summarization fails, do not write a partial batch. Report the failure count and artifact paths concisely.
- After all calls succeed, persist summaries with SQLite parameter binding in one transaction. Update by `article_key` only where the summary is still NULL or blank.
- Re-query the same fixed half-open window and require zero eligible blank summaries before synthesis. Reruns must be idempotent.

## 2. Synthesize the brief

Read the prepared-evidence JSON, the summarized news rows in the fixed handoff window, and relevant `prices` rows. Prefer primary sources and material facts. Deduplicate repeated URLs and syndicated versions. Distinguish facts from interpretation.

Write:

1. `report_output`: a durable Markdown report with source collection counts, market snapshot, portfolio/watchlist events, and the most important market, macro, policy, technology, and business developments.
2. `slack_brief_output`: a concise Slack-mrkdwn brief. Use `*single asterisks*` for bold and `<url|label>` links. Do not use Markdown headings or tables.

Cite factual claims with direct source URLs from SQLite. Do not cite `finnhub.io/api/news` proxy URLs when an original source URL is available.

## 3. Return result

Do not call Slack. Return the exact contents of `slack_brief_output` as the response so the cron delivery layer posts it once. If any required phase fails, return one concise failure message naming the phase and diagnostic artifact path instead of a partial brief.
