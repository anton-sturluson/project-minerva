from contextlib import nullcontext
from datetime import date
from uuid import uuid4

from harness.ideas import workflow


def test_resume_skips_ready_and_gaps_and_processes_only_limit(tmp_path, monkeypatch):
    run_id = uuid4()
    monkeypatch.setenv("BRAVE_API_KEY", "test-not-used")
    monkeypatch.setenv("GEMINI_API_KEY", "test-not-used")
    monkeypatch.setattr(workflow.store, "run_lock", lambda _: nullcontext())
    monkeypatch.setattr(
        workflow.store,
        "get_run",
        lambda _: {"id": run_id, "issue_date": date(2026, 9, 30)},
    )
    monkeypatch.setattr(workflow.store, "run_folder", lambda _: tmp_path)
    rows = [
        {"ordinal": 1, "state": "ready"},
        {"ordinal": 2, "state": "gap"},
        {"ordinal": 3, "state": "pending"},
        {"ordinal": 4, "state": "pending"},
    ]
    monkeypatch.setattr(workflow.store, "items", lambda _: rows)
    calls = []
    monkeypatch.setattr(
        workflow,
        "discover",
        lambda _, ordinal, **kw: (
            calls.append(("discover", ordinal)) or {"url": "source"}
        ),
    )
    monkeypatch.setattr(
        workflow, "extract", lambda _, ordinal, **kw: calls.append(("extract", ordinal))
    )
    monkeypatch.setattr(
        workflow.store,
        "status",
        lambda _: {
            "counts": {"ready": 2, "pending": 1, "sourced": 0, "failed": 0, "gap": 1}
        },
    )
    result = workflow.resume(run_id, limit=1)
    assert calls == [("discover", 3), ("extract", 3)]
    assert result["outcome"] == "partial"


def test_feed_accepts_html_encoded_roster_bullets(monkeypatch):
    body='<p>&#128313; Acme (ACM US) by Alpha Fund</p>'
    xml=f'<rss xmlns:content="http://purl.org/rss/1.0/modules/content/"><channel><item><link>https://hfbestideas.substack.com/p/test</link><pubDate>Wed, 30 Sep 2026 12:00:00 GMT</pubDate><content:encoded><![CDATA[{body}]]></content:encoded></item></channel></rss>'
    class Response:
        content=xml.encode()
        def raise_for_status(self):pass
    monkeypatch.setattr(workflow.httpx,'get',lambda *a,**kw:Response())
    issue,readable=workflow.fetch_issue()
    assert issue['roster'][0]['company']=='Acme'
    assert issue['date']=='2026-09-30'
    assert b'feed_url:' in readable
