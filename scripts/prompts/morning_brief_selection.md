# Morning brief article selection

Read every summary and select each article that meets the criteria below. Do not select from titles or URLs alone or impose a quota. A later pass will query the selected articles, group related coverage, and classify portfolio/watchlist items.

Include only news that could materially change our estimate of a business's long-term value or risk: portfolio/watchlist fundamentals; demand, economics, or moat; management or incentives; capital allocation; regulation; balance-sheet or solvency risk; material macro or industry demand, cost, rate, or tail-risk changes; and credible evidence against the thesis.

Exclude price moves or technicals, targets, ratings without new facts, promotional picks, predictions, listicles, clickbait, low-substance commentary, and recycled or syndicated stories without new information.

Prefer filings, investor relations, and regulators, then WSJ, Economist, and Reuters. Use lower-quality sources only for unique material facts. Materiality comes first; source quality breaks ties.

Return only JSONL, one line per selected article:

{"article_key":"exact-key-from-input","rationale":"why this article could change long-term value or risk"}

If nothing qualifies, return `{"article_key":null,"rationale":"No article qualifies."}`.
