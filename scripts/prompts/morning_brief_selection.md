# Morning brief article selection

Select every material development supported by the article summaries in this batch. Read each summary; do not select from titles or URLs alone. Do not impose a quota. A later synthesis pass will group related selections across batches and classify portfolio/watchlist items.

Include only news that could materially change our estimate of a business's long-term value or risk: portfolio/watchlist fundamentals; demand, economics, or moat; management or incentives; capital allocation; regulation; balance-sheet or solvency risk; material macro or industry demand, cost, rate, or tail-risk changes; and credible evidence against the thesis.

Exclude price moves or technicals, targets, ratings without new facts, promotional picks, predictions, listicles, clickbait, low-substance commentary, and recycled or syndicated stories without new information.

Prefer filings, investor relations, and regulators, then WSJ, Economist, and Reuters. Use lower-quality sources only for unique material facts. Materiality comes first; source quality breaks ties.

Return JSON only, with no Markdown fence or commentary:

{"selected_developments":[{"takeaway":"concise factual investor takeaway","article_keys":["exact-key-from-input"],"urls":["source URL from input"],"materiality":"why this could change long-term value or risk"}]}

Group duplicate or follow-up coverage within this batch into one development. Use only exact article keys and URLs from the input. Return an empty `selected_developments` array when nothing qualifies.
