from uuid import uuid4

from harness.ideas import publication


def test_renderer_only_publishes_ready_original_equity_views(monkeypatch):
    monkeypatch.setattr(publication, "checked_view", lambda row, run: row["view"])
    monkeypatch.setattr(
        publication.store, "get_run", lambda _: {"issue_date": "2026-09-30"}
    )
    row = {
        "state": "ready",
        "company": "Acme",
        "fund": "Alpha",
        "document": {
            "url": "https://manager.com/letter",
            "identity": {"period": "Q2 2026"},
        },
        "view": {
            "instrument": "equity",
            "stance": "bull",
            "action": "not stated",
            "claims": [{"text": "Pricing supports margins."}],
        },
    }
    monkeypatch.setattr(
        publication.store,
        "items",
        lambda _: [row, {"state": "gap", "company": "Hidden"}],
    )
    text = publication.render(uuid4())
    assert "Acme" in text and "Hidden" not in text
    assert "<https://manager.com/letter|Original manager letter>" in text
    assert "not stated" not in text and "summary.md" not in text


def test_empty_digest_has_no_publication(monkeypatch):
    monkeypatch.setattr(publication, "render", lambda _: "")
    assert publication.prepare(uuid4(), uuid4()) == "NO_REPLY"


def test_reconciliation_requires_exact_content_route_and_fresh_receipt(
    tmp_path, monkeypatch
):
    from contextlib import contextmanager
    from datetime import datetime, timezone

    job_id = uuid4()
    run_id = uuid4()
    route = {"channel": "slack", "to": "channel:C1", "threadId": "1.2"}
    prepared = datetime(2026, 10, 3, 12, tzinfo=timezone.utc)
    record = {
        "digest": "abc",
        "run_id": run_id,
        "route": route,
        "prepared_at": prepared,
    }
    (tmp_path / "publications").mkdir()
    (tmp_path / "publications/abc.slack.txt").write_text("Exact digest")
    monkeypatch.setattr(publication.store, "get_run", lambda _: {"id": run_id})
    monkeypatch.setattr(publication.store, "run_folder", lambda _: tmp_path)
    updates = []

    class Connection:
        def execute(self, sql, args=None):
            if sql.startswith("UPDATE"):
                updates.append((sql, args))
            return self

        def fetchall(self):
            return [record]

    @contextmanager
    def connect():
        yield Connection()

    monkeypatch.setattr(publication.store, "connect", connect)
    entry = {
        "summary": "Exact digest",
        "delivered": True,
        "deliveryStatus": "delivered",
        "ts": prepared.timestamp() * 1000 + 1000,
        "tsIso": "2026-10-03T12:00:01Z",
        "runId": "r1",
        "delivery": {"resolved": route},
    }
    monkeypatch.setattr(publication, "gateway_json", lambda *args: {"entries": [entry]})
    assert publication.reconcile(job_id)["confirmed_deliveries"] == 1
    assert updates[-1][1][0].obj.keys() == {"run_id", "delivered_at", "route"}
    entry["delivery"]["resolved"] = {**route, "to": "channel:WRONG"}
    assert publication.reconcile(job_id)["confirmed_deliveries"] == 0
    entry["delivery"]["resolved"] = route
    entry["summary"] = "A summary of the digest"
    assert publication.reconcile(job_id)["confirmed_deliveries"] == 0
    entry["summary"] = "Exact digest"
    entry["ts"] = prepared.timestamp() * 1000 - 1000
    assert publication.reconcile(job_id)["confirmed_deliveries"] == 0


import os

import pytest


@pytest.mark.skipif(
    not os.getenv("MINERVA_TEST_DATABASE_URL"),
    reason="explicit Postgres test database required",
)
def test_postgres_duplicate_and_receipt_lifecycle(tmp_path, monkeypatch):
    from datetime import datetime, timezone

    from psycopg.types.json import Jsonb

    from harness.ideas import store

    monkeypatch.setenv("MINERVA_DATABASE_URL", os.environ["MINERVA_TEST_DATABASE_URL"])
    monkeypatch.setenv("MINERVA_IDEAS_ROOT", str(tmp_path))
    store.initialize()
    monkeypatch.setattr(publication, "checked_view", lambda row, run: row["view"])
    run_id = uuid4()
    job_id = uuid4()
    route = {"channel": "slack", "to": "channel:TEST", "threadId": "test"}
    monkeypatch.setattr(
        publication,
        "gateway_json",
        lambda *a: {"delivery": {"mode": "announce", **route}},
    )
    store.import_issue(
        {
            "url": "https://example.org/test",
            "date": "2026-09-30",
            "roster": [{"company": "Acme", "fund": "Alpha"}],
        },
        run_id=run_id,
    )
    try:
        with store.connect() as conn:
            conn.execute(
                "UPDATE minerva_ideas.items SET state='ready',document=%s,view=%s WHERE run_id=%s",
                (
                    Jsonb(
                        {
                            "url": "https://manager.example.org/original.pdf",
                            "identity": {"period": "Q2 2026"},
                        }
                    ),
                    Jsonb(
                        {
                            "instrument": "equity",
                            "stance": "bull",
                            "action": "not stated",
                            "claims": [{"text": "Test claim; never sent."}],
                        }
                    ),
                    run_id,
                ),
            )
        text = publication.prepare(run_id, job_id)
        with pytest.raises(ValueError, match="may already"):
            publication.prepare(run_id, job_id)
        entry = {
            "summary": text,
            "delivered": True,
            "deliveryStatus": "delivered",
            "ts": datetime.now(timezone.utc).timestamp() * 1000 + 1000,
            "tsIso": "test",
            "runId": "test",
            "delivery": {"resolved": route},
        }
        monkeypatch.setattr(
            publication, "gateway_json", lambda *a: {"entries": [entry]}
        )
        assert publication.reconcile(job_id)["confirmed_deliveries"] == 1
        monkeypatch.setattr(
            publication,
            "gateway_json",
            lambda *a: {"delivery": {"mode": "announce", **route}},
        )
        assert publication.prepare(run_id, job_id) == "NO_REPLY"
    finally:
        with store.connect() as conn:
            conn.execute(
                "DELETE FROM minerva_ideas.publications WHERE run_id=%s", (run_id,)
            )
            conn.execute("DELETE FROM minerva_ideas.items WHERE run_id=%s", (run_id,))
            conn.execute("DELETE FROM minerva_ideas.runs WHERE id=%s", (run_id,))


def test_render_gate_rejects_wrong_company_even_if_marked_ready(tmp_path, monkeypatch):
    from datetime import date

    monkeypatch.setattr(publication.store, "run_folder", lambda _: tmp_path)
    monkeypatch.setattr(
        publication,
        "load_sections",
        lambda *a: [{"id": "p1", "text": "Alpha Fund Q2 2026 Acme investment thesis."}],
    )
    identity = {
        "accepted": True,
        "reason": "test",
        "fund": "Alpha Fund",
        "company": "Acme",
        "period": "Q2 2026",
        "period_end": "2026-06-30",
        "publisher_block": "p1",
        "fund_block": "p1",
        "company_block": "p1",
        "period_block": "p1",
    }
    row = {
        "company": "Different Issuer",
        "fund": "Alpha Fund",
        "symbol": "DIF US",
        "document": {"identity": identity},
    }
    with pytest.raises(ValueError, match="company"):
        publication.checked_view(row, {"issue_date": date(2026, 9, 30)})


def test_truncated_summary_needs_full_bound_session_output(tmp_path,monkeypatch):
    from contextlib import contextmanager
    from datetime import datetime,timezone
    job_id=uuid4();run_id=uuid4();now=datetime.now(timezone.utc)
    text='Original-source digest '+('x'*2200)
    (tmp_path/'publications').mkdir();(tmp_path/'publications/d.slack.txt').write_text(text)
    route={'channel':'slack','to':'channel:T','threadId':'t'}
    record={'digest':'d','run_id':run_id,'route':route,'prepared_at':now}
    class Connection:
        def execute(self,*a):return self
        def fetchall(self):return [record]
    @contextmanager
    def connect():yield Connection()
    monkeypatch.setattr(publication.store,'connect',connect)
    monkeypatch.setattr(publication.store,'get_run',lambda _:{})
    monkeypatch.setattr(publication.store,'run_folder',lambda _:tmp_path)
    entry={'summary':text[:2000]+'…','delivered':True,'deliveryStatus':'delivered','ts':now.timestamp()*1000+1000,'delivery':{'resolved':route}}
    monkeypatch.setattr(publication,'gateway_json',lambda *a:{'entries':[entry]})
    monkeypatch.setattr(publication,'session_output',lambda *a:'Different full content')
    assert publication.reconcile(job_id)['confirmed_deliveries']==0
    monkeypatch.setattr(publication,'session_output',lambda *a:text)
    assert publication.reconcile(job_id)['confirmed_deliveries']==1


def test_session_export_must_belong_to_the_same_job(tmp_path):
    session_id=uuid4()
    with pytest.raises(ValueError,match='bound'):
        publication.session_output({'sessionId':str(session_id),'sessionKey':f'agent:main:cron:{uuid4()}:run:{session_id}'},tmp_path,uuid4())
