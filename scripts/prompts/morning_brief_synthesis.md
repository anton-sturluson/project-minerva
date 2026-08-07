# Morning brief synthesis contract

The collection script has already populated prepared evidence, `news`, and `prices`. Do not repeat collection, browse the web, delegate synthesis or writing, or post to Slack with a messaging tool. The sole permitted delegation is the one fresh GPT Terra article-selection turn in Section 3: Terra selects; Sol synthesizes and writes.

## 1. Validate the input

Read the `synthesis-handoff.json` path printed by `scripts/run_morning_brief.sh`. Treat this prompt as the versioned synthesis contract. Before accessing the database, require a JSON object with `status` set to `ready`; require `date`, `window_start`, `window_end`, `db`, `prepared_evidence`, `evidence_stats`, `collector_stats`, `holdings_path`, `watchlist_path`, `instructions`, and `slack_brief_output` with the expected types; and require `instructions` to identify this prompt. Stop with a concise schema/version error if validation fails. Do not infer missing values.

Use `window_start` and `window_end` exactly as provided with today's collected data.

## 2. Complete pending summaries safely

- Select eligible `news` rows using `published_at` as UTC epoch seconds in the fixed half-open interval from `window_start` inclusive to `window_end` exclusive. The timestamps represent the previous run date at 04:00 through the run date at 04:00 in `America/New_York`. Do not use calendar-date prefix matching or change these bounds.
- Process only rows where `content` is non-empty and `summary` is NULL or blank.
- For each row, pipe `content` on stdin to:

```bash
uv run minerva summarize --model gemini-3.6-flash --thinking high
```

- Run no more than four summarization subprocesses at once. Keep article content and generated summaries in memory; do not write article or summary files.
- If any summarization fails, do not write a partial batch. Report the failure count and artifact paths concisely.
- After all calls succeed, persist summaries with parameter binding in one SQLite transaction. Update by `article_key` only where the summary is still NULL or blank.
- Re-query the same fixed half-open window and require zero eligible blank summaries before synthesis. Reruns must be idempotent.

## 3. Have Terra select the developments

Read the prepared-evidence JSON, relevant `prices` rows, and the complete summary of every article in the collection period. Do not select from headlines or URLs alone. Confirm that the number of summaries read matches the total article count in `evidence_stats`; otherwise stop and report both counts and the diagnostic artifact path.

Before writing, make exactly one fresh Terra agent turn. Give it a unique new session ID and invoke it without `--deliver` or any other delivery option:

```bash
openclaw agent --agent main --model terra --thinking high --session-id "$fresh_session_id" --message "$selection_prompt"
```

The single message must contain the portfolio/watchlist identities and the complete summary set, with exactly one object per article containing `article_key`, `url`, `title`, `source`, `published_at`, and `summary`. It must also instruct Terra to return JSON only as `{"selected_developments": [{"section": "portfolio_watchlist|worth_knowing", "takeaway": "...", "article_keys": ["..."], "urls": ["..."], "materiality": "..."}]}` under this selection policy:

- Include news only if it could materially change our estimate of a business's long-term value or risk. This includes portfolio/watchlist fundamental developments; new evidence about demand, economics or moat, management or incentives, capital allocation, regulation, or balance-sheet/solvency risk; macro or industry changes that materially affect demand, costs, rates, or tail risk; and credible evidence against the thesis, including thesis-break signals.
- Exclude stock-price moves, technicals, price targets, rating changes without new facts, promotional picks, predictions, listicles, clickbait, low-substance commentary, and recycled or syndicated stories without new information.
- Use filings, IR, and regulators first, followed by WSJ, Economist, and Reuters. Use lower-quality sources only for unique material facts. Materiality comes first; source quality breaks ties.
- Group duplicate and follow-up coverage into one development grounded in its article keys and URLs. Portfolio/watchlist items may cover only companies in the supplied holdings or watchlist; reject unrelated ticker-text matches.

Do not retry, ask Terra a follow-up, or make another delegated agent call. Treat every article absent from Terra's `selected_developments` as excluded. Sol may group and rank Terra's selections and must write every selected qualifying development without an arbitrary bullet limit, but must not add an excluded article, article key, URL, or development. Clearly label rumors and third-party interpretations.

## 4. Write the Slack brief

Write the canonical `slack_brief_output` from Terra's shortlist. Do not create a separate report or memo.

Write exactly these three sections in the order shown, with no other text or sections:

```text
_Crawler:_ {total articles} — {source} {count} · {source} {count} · ...; {successful}/{total} collectors succeeded, {failed} failed.

_Portfolio / Watchlist Events_
• _{Company/ticker — takeaway}:_ Explain what happened, the important facts, and why it matters. Cite the original sources.

_Worth Knowing Today_
• _{Investor takeaway}:_ Explain the development, why it matters to investors, and any important uncertainty. Cite the original sources.
```

If nothing material occurred for the portfolio or watchlist, use the approved fallback:

```text
• No material portfolio or watchlist developments during the collection period.
```

Get final article and per-source counts from the verified window query and collector successes and failures from `collector_stats`. Cite factual claims with direct source URLs from SQLite, linking to original articles rather than `finnhub.io/api/news` proxy pages when possible. Do not use Markdown headings or tables.

## 5. Return the result

Do not call Slack or any messaging tool. Return the exact contents of `slack_brief_output`, with no preamble, commentary, or code fence, so the cron delivery layer posts it once. If a required step explicitly listed in Sections 1-4 fails, return one concise failure message naming the phase and diagnostic artifact path instead of a partial brief. Only those failures are fatal. Do not invent or invoke validation commands not listed in this contract; if an unlisted command fails, correct or skip it rather than aborting when `slack_brief_output` can still be produced and read.
