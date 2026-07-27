# Controlled news E2E collector

You are the only collector in a deliberately isolated end-to-end test.

- Article URL: `{{ARTICLE_URL}}`
- Scratch database: `{{DB}}`
- Run date: `{{DATE}}`
- Fixed source ID: `e2e-collector`

Fetch exactly the public article URL above. Extract the article into normalized
Markdown or plain text: preserve the substantive body, remove navigation,
advertising, cookie text, and other page chrome. Do not send raw HTML.

Construct exactly one JSON object with these fields:

- `title`: the article's real, non-empty title
- `source_id`: exactly `e2e-collector`
- `url`: exactly `{{ARTICLE_URL}}`
- `published_at`: the article's publication date/time when available; if the
  page has no publication value, use `{{DATE}}`
- `content`: the normalized non-empty Markdown/text body
- optional `section`: `e2e-controlled-article`
- optional `collected_at`: current ISO-8601 UTC timestamp

Pipe the JSON object directly on stdin to this exact command:

```bash
cd {{ROOT_Q}} && printf '%s\n' "$article_json" | {{MINERVA}} news ingest --input - --db {{DB_Q}}
```

You may use a different safe JSON-producing shell construct, but it must end in
the same direct pipe to `news ingest --input -`. Do not create an intermediate
article, JSON, Markdown, or text file. The scratch SQLite DB is the only
persistent collector output. Confirm the ingest command returns `inserted`,
`updated`, or `duplicate`; otherwise fail. Do not access any other database.
Do not invoke Slack or any messaging tool.
