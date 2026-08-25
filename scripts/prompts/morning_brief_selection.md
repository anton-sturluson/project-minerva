# Morning brief article selection

Read every summary and select each article that meets the criteria below. Do not select from titles or URLs alone or impose a quota. A later pass will query the selected articles, group related coverage, and classify portfolio/watchlist items.

Use `PORTFOLIO_UNIVERSE_JSON` when provided; each entry's `sources` field identifies holding/watchlist membership. Treat membership as an important positive relevance signal, not automatic selection. Include articles with material direct or read-through relevance to these securities when they meet the criteria below.

Include only news that could materially change our estimate of a business's long-term value or risk: portfolio/watchlist fundamentals; demand, economics, or moat; management or incentives; capital allocation; regulation; balance-sheet or solvency risk; material macro or industry demand, cost, rate, or tail-risk changes; and credible evidence against the thesis. Include evidence-backed durable business, technological, social, demographic, labor, institutional, or resource shifts when they can materially reshape demand, productivity, costs, incentives, or risk, including indirectly or over the long term.

Exclude price-movement stories, technical analysis, price targets, ratings without new evidence, generic promotional picks, predictions, listicles, clickbait, low-substance commentary, and recycled or syndicated stories without new information. A stock-pick article may qualify when it offers a specific, evidence-backed variant perception that could change our view.

Prefer filings, investor relations, and regulators, then WSJ, Economist, and Reuters. Use lower-quality sources only for unique material facts. Materiality comes first; source quality breaks ties.

Return only JSONL, one line per selected article:

{"article_key":"exact-key-from-input","rationale":"why this article could change long-term value or risk"}

If nothing qualifies, return `{"article_key":null,"rationale":"No article qualifies."}`.
