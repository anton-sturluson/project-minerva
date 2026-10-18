from harness.ideas import workflow


def test_resume_selection_preserves_ready_and_requires_explicit_gap_retry() -> None:
    """Resuming selects only eligible ordinals and respects the requested limit."""
    rows: list[dict] = [
        {"ordinal": 1, "state": "ready"},
        {"ordinal": 2, "state": "gap"},
        {"ordinal": 3, "state": "pending"},
        {"ordinal": 4, "state": "failed"},
        {"ordinal": 5, "state": "sourced"},
    ]
    assert workflow.selected_ordinals(rows, 50, False) == [3, 4, 5]
    assert workflow.selected_ordinals(rows, 2, True) == [2, 3]
    assert workflow.selected_ordinals(rows[:2], 50, False) == []


def test_feed_accepts_html_encoded_roster_bullets(monkeypatch):
    body = "<p>&#128313; Acme (ACM US) by Alpha Fund</p>"
    xml = f'<rss xmlns:content="http://purl.org/rss/1.0/modules/content/"><channel><item><link>https://hfbestideas.substack.com/p/test</link><pubDate>Wed, 30 Sep 2026 12:00:00 GMT</pubDate><content:encoded><![CDATA[{body}]]></content:encoded></item></channel></rss>'

    class Response:
        content = xml.encode()

        def raise_for_status(self):
            pass

    monkeypatch.setattr(workflow.httpx, "get", lambda *a, **kw: Response())
    issue, readable = workflow.fetch_issue()
    assert issue["roster"][0]["company"] == "Acme"
    assert issue["date"] == "2026-09-30"
    assert b"feed_url:" in readable
