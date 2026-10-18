import os
from pathlib import Path
from uuid import uuid4

import pytest

from harness.ideas import store
from harness.ideas.roster import parse_roster


def test_roster_preserves_repeated_fund_views():
    rows = parse_roster(
        "<p>🔹 Acme (ACM US) by Alpha</p><p>🔹 Acme (ACM US) by Beta</p>"
    )
    assert [r.fund for r in rows] == ["Alpha", "Beta"]
    assert rows[0].symbol == "ACM US"


def test_artifacts_immutable_and_portable(tmp_path):
    assert store.write_artifact(tmp_path, "research/a.txt", b"one") == "research/a.txt"
    store.write_artifact(tmp_path, "research/a.txt", b"one")
    with pytest.raises(ValueError):
        store.write_artifact(tmp_path, "research/a.txt", b"two")
    assert (tmp_path / "research/a.txt").read_bytes() == b"one"


@pytest.mark.skipif(
    not os.getenv("MINERVA_TEST_DATABASE_URL"),
    reason="Postgres integration test requires explicit test database",
)
def test_postgres_import_is_atomic_and_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("MINERVA_DATABASE_URL", os.environ["MINERVA_TEST_DATABASE_URL"])
    monkeypatch.setenv("MINERVA_IDEAS_ROOT", str(tmp_path))
    store.initialize()
    run_id = uuid4()
    issue = {
        "url": "https://hfbestideas.substack.com/p/test",
        "date": "2026-09-30",
        "roster": [
            {"company": "Acme", "fund": "Alpha"},
            {"company": "Acme", "fund": "Beta"},
        ],
    }
    try:
        store.import_issue(issue, run_id=run_id)
        store.import_issue(issue, run_id=run_id)
        assert len(store.items(run_id)) == 2
        assert store.status(run_id)["counts"]["pending"] == 2
        issue["roster"][0]["fund"] = "Changed"
        with pytest.raises(ValueError):
            store.import_issue(issue, run_id=run_id)
        assert store.items(run_id)[0]["fund"] == "Alpha"
    finally:
        with store.connect() as conn:
            conn.execute("DELETE FROM minerva_ideas.items WHERE run_id=%s", (run_id,))
            conn.execute("DELETE FROM minerva_ideas.runs WHERE id=%s", (run_id,))


@pytest.mark.skipif(
    not os.getenv("MINERVA_TEST_DATABASE_URL"),
    reason="explicit Postgres test database required",
)
def test_run_lock_releases_after_failure(monkeypatch):
    monkeypatch.setenv("MINERVA_DATABASE_URL", os.environ["MINERVA_TEST_DATABASE_URL"])
    run_id = uuid4()
    with pytest.raises(RuntimeError):
        with store.run_lock(run_id):
            with pytest.raises(ValueError, match="already"):
                with store.run_lock(run_id):
                    pass
            raise RuntimeError("interrupted")
    with store.run_lock(run_id):
        pass


@pytest.mark.skipif(
    not os.getenv("MINERVA_TEST_DATABASE_URL"),
    reason="explicit Postgres test database required",
)
def test_fresh_run_preserves_previous_run_and_resume_reuses_latest(
    tmp_path, monkeypatch
):
    from harness.ideas import workflow

    monkeypatch.setenv("MINERVA_DATABASE_URL", os.environ["MINERVA_TEST_DATABASE_URL"])
    monkeypatch.setenv("MINERVA_IDEAS_ROOT", str(tmp_path))
    issue = {
        "url": f"https://example.com/issue/{uuid4()}",
        "date": "2026-09-30",
        "roster": [{"company": "Acme", "fund": "Alpha", "symbol": ""}],
    }
    monkeypatch.setattr(
        workflow, "fetch_issue", lambda issue_url=None: (issue, b"feed: test\n")
    )
    monkeypatch.setattr(workflow, "resume", lambda run_id, **kwargs: run_id)
    store.initialize()
    ids = []
    try:
        first = workflow.start()
        ids.append(first)
        second = workflow.start(fresh=True)
        ids.append(second)
        assert first != second
        reused = workflow.start()
        if reused not in ids:
            ids.append(reused)
        assert reused == second
        assert len(store.items(first)) == len(store.items(second)) == 1
        assert (
            store.run_folder(store.get_run(first)) / "research/issue.json"
        ).is_file()
    finally:
        with store.connect() as conn:
            for run_id in ids:
                conn.execute(
                    "DELETE FROM minerva_ideas.items WHERE run_id=%s", (run_id,)
                )
                conn.execute("DELETE FROM minerva_ideas.runs WHERE id=%s", (run_id,))


@pytest.mark.skipif(
    not os.getenv("MINERVA_TEST_DATABASE_URL"),
    reason="explicit Postgres test database required",
)
def test_prior_source_candidates_exclude_future_issues_and_other_funds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reuse URLs with exact fund attribution without inheriting future or sibling sources."""
    from datetime import date
    from uuid import UUID

    from psycopg.types.json import Jsonb

    monkeypatch.setenv("MINERVA_DATABASE_URL", os.environ["MINERVA_TEST_DATABASE_URL"])
    monkeypatch.setenv("MINERVA_IDEAS_ROOT", str(tmp_path))
    fund: str = f"Example Fund {uuid4()}"
    sibling: str = fund + " Global"
    ids: list[UUID] = []
    store.initialize()
    try:
        issue_date: str
        name: str
        suffix: str
        for issue_date, name, suffix in (
            ("2026-09-30", fund, "old"),
            ("2026-10-07", fund, "recent"),
            ("2026-10-07", fund, "recent"),
            ("2026-09-23", fund, "oldest"),
            ("2026-10-07", sibling, "sibling"),
            ("2027-01-07", fund, "future"),
        ):
            run_id: UUID = store.import_issue(
                {
                    "url": f"https://example.com/issue/{uuid4()}",
                    "date": issue_date,
                    "roster": [{"company": "Acme", "fund": name}],
                }
            )
            ids.append(run_id)
            with store.connect() as conn:
                conn.execute(
                    "UPDATE minerva_ideas.items SET state='ready',document=%s WHERE run_id=%s",
                    (
                        Jsonb(
                            {
                                "url": f"https://example.com/{suffix}.pdf",
                                "identity": {
                                    "period": issue_date,
                                    "period_end": issue_date,
                                },
                            }
                        ),
                        run_id,
                    ),
                )
        hints: list[dict[str, str]] = store.source_hints([fund], date(2026, 10, 14))
        assert [hint["url"] for hint in hints] == [
            "https://example.com/recent.pdf",
            "https://example.com/old.pdf",
        ]
        assert all(hint["fund"] == fund for hint in hints)
        assert all(set(hint) == {"fund", "url", "period"} for hint in hints)
    finally:
        with store.connect() as conn:
            conn.execute("DELETE FROM minerva_ideas.items WHERE run_id=ANY(%s)", (ids,))
            conn.execute("DELETE FROM minerva_ideas.runs WHERE id=ANY(%s)", (ids,))
