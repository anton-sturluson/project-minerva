from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest

from harness.ideas import publication as p


def test_thread_parts_preserve_full_unicode_text_and_links():
    text = (
        "Company 🧵\n• Supported thesis.\n<https://example.com/letter|Original>\n\n"
        * 140
    ).strip()
    parts = p.thread_parts(text)
    assert len(parts) > 1 and "".join(parts) == text
    assert all(len(part.encode()) <= 3000 for part in parts)
    assert all("<https://example.com/letter|Original>" in part for part in parts)
    with pytest.raises(ValueError):
        p.thread_parts("x" * 3001)


def test_sender_requires_acknowledgement_and_routes_replies(tmp_path, monkeypatch):
    import json

    calls = []
    output = {
        "dryRun": False,
        "payload": {"ok": True, "result": {"messageId": "12.34", "channelId": "C1"}},
    }

    def run(argv, **kwargs):
        calls.append(argv)
        return SimpleNamespace(stdout=json.dumps(output))

    monkeypatch.setattr(p.subprocess, "run", run)
    route = {"to": "channel:C1", "accountId": "work"}
    receipt = p.slack_send(route, "Body", tmp_path, "good.json", parent="1.2")
    assert receipt["thread_id"] == "1.2"
    assert calls[0][-2:] == ["--reply-to", "1.2"]
    assert "--account" in calls[0]
    output["payload"]["result"]["channelId"] = "WRONG"
    with pytest.raises(ValueError, match="confirm"):
        p.slack_send(route, "Body", tmp_path, "wrong.json")


@pytest.mark.parametrize("fail_at", [None, 0, 2])
def test_thread_sequence_and_partial_failure(tmp_path, monkeypatch, fail_at):
    body = ("Company\n" + "Evidence " * 70 + "\n") * 12
    prepared = {
        "digest": "abc",
        "route": {"to": "channel:C1"},
        "text": "🧵 Manager Ideas - 2026-09-30\n\n" + body,
    }
    monkeypatch.setattr(p, "prepare_publication", lambda *a, **kw: prepared)
    monkeypatch.setattr(p.store, "get_run", lambda _: {})
    monkeypatch.setattr(p.store, "run_folder", lambda _: tmp_path)
    writes, calls = [], []
    monkeypatch.setattr(
        p, "save_thread_receipt", lambda d, r, s: writes.append((deepcopy(r), s))
    )

    def send(route, text, folder, artifact, *, parent=None):
        index = len(calls)
        calls.append((text, parent))
        assert writes[-1][0]["inflight"] is not None
        if index == fail_at:
            raise TimeoutError("Unknown send outcome")
        return {"message_id": f"10.{index}", "channel_id": "C1", "thread_id": parent}

    monkeypatch.setattr(p, "slack_send", send)
    if fail_at is None:
        result = p.publish_thread(uuid4(), uuid4())
        assert writes[-1][1] == "delivered"
        assert calls[0] == ("🧵 Manager Ideas - 2026-09-30", None)
        assert all(parent == "10.0" for _, parent in calls[1:])
        assert "".join(text for text, _ in calls[1:]) == body
        assert len(result["replies"]) == len(calls) - 1
    else:
        with pytest.raises(ValueError, match="uncertain"):
            p.publish_thread(uuid4(), uuid4())
        assert writes[-1][1] == "unknown"
        assert len(calls) == fail_at + 1
        if fail_at == 2:
            assert writes[-1][0]["parent"]["message_id"] == "10.0"
            assert len(writes[-1][0]["replies"]) == 1


def test_confirmed_duplicate_sends_nothing(monkeypatch):
    monkeypatch.setattr(p, "prepare_publication", lambda *a, **kw: None)
    monkeypatch.setattr(p, "slack_send", lambda *a, **kw: pytest.fail("duplicate send"))
    assert p.publish_thread(uuid4(), uuid4()) is None


def test_thread_prepare_requires_disabled_announce_and_no_fixed_thread(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(p, "render", lambda _: "Digest")
    monkeypatch.setattr(p.store, "get_run", lambda _: {"issue_date": "2026-09-30"})
    job = {
        "payload": {"kind": "command"},
        "delivery": {"mode": "announce", "channel": "slack", "to": "channel:C1"},
    }
    monkeypatch.setattr(p, "gateway_json", lambda *a: job)
    with pytest.raises(ValueError, match="mode=none"):
        p.prepare_publication(uuid4(), uuid4(), threaded=True)
    job["delivery"].update(mode="none", threadId="old")
    with pytest.raises(ValueError, match="no fixed"):
        p.prepare_publication(uuid4(), uuid4(), threaded=True)


@pytest.mark.skipif(
    not __import__("os").getenv("MINERVA_TEST_DATABASE_URL"),
    reason="explicit Postgres test database required",
)
def test_postgres_thread_receipts_and_ambiguous_retry(tmp_path, monkeypatch):
    import os

    from harness.ideas import store

    monkeypatch.setenv("MINERVA_DATABASE_URL", os.environ["MINERVA_TEST_DATABASE_URL"])
    monkeypatch.setenv("MINERVA_IDEAS_ROOT", str(tmp_path))
    store.initialize()
    run_id, job_id = uuid4(), uuid4()
    store.import_issue(
        {
            "url": "https://example.com/thread-test",
            "date": "2026-09-30",
            "roster": [{"company": "Acme", "fund": "Alpha"}],
        },
        run_id=run_id,
    )
    monkeypatch.setattr(p, "render", lambda _: "Full verified summary.\n" * 250)
    monkeypatch.setattr(
        p,
        "gateway_json",
        lambda *a: {
            "payload": {"kind": "command"},
            "delivery": {"mode": "none", "channel": "slack", "to": "channel:TEST"},
        },
    )
    sends = []
    fail = False

    def send(route, text, folder, artifact, *, parent=None):
        sends.append(parent)
        if fail and parent:
            raise TimeoutError()
        return {
            "message_id": f"1.{len(sends)}",
            "channel_id": "TEST",
            "thread_id": parent,
        }

    monkeypatch.setattr(p, "slack_send", send)
    try:
        with store.run_lock(run_id):
            receipt = p.publish_thread(run_id, job_id)
        assert receipt["parent"]["message_id"] == "1.1"
        assert sends[0] is None and all(x == "1.1" for x in sends[1:])
        n = len(sends)
        assert p.publish_thread(run_id, job_id) is None and len(sends) == n
        fail = True
        other_job = uuid4()
        with pytest.raises(ValueError, match="uncertain"):
            p.publish_thread(run_id, other_job)
        n = len(sends)
        with pytest.raises(ValueError, match="may already"):
            p.publish_thread(run_id, other_job)
        assert len(sends) == n
        with store.connect() as conn:
            row = conn.execute(
                "SELECT state,receipt FROM minerva_ideas.publications WHERE job_id=%s",
                (other_job,),
            ).fetchone()
        assert row["state"] == "unknown" and row["receipt"]["parent"]["message_id"]
        assert row["receipt"]["inflight"] == "reply-0"
    finally:
        with store.connect() as conn:
            conn.execute(
                "DELETE FROM minerva_ideas.publications WHERE run_id=%s", (run_id,)
            )
            conn.execute("DELETE FROM minerva_ideas.items WHERE run_id=%s", (run_id,))
            conn.execute("DELETE FROM minerva_ideas.runs WHERE id=%s", (run_id,))
