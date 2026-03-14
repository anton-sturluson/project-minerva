"""Tests for JobWatchDB storage layer."""

from __future__ import annotations

from pathlib import Path

import pytest

from jobwatch.db import JobWatchDB


@pytest.fixture
def db(tmp_path: Path) -> JobWatchDB:
    db_path: Path = tmp_path / "test.db"
    database: JobWatchDB = JobWatchDB(db_path)
    database.init_db()
    return database


@pytest.fixture
def seeded_db(db: JobWatchDB) -> JobWatchDB:
    """DB with one company and one active posting."""
    db.ensure_company("acme", "Acme Corp", "greenhouse", "acme", "https://acme.com")
    posting: dict = {
        "ats_job_id": "job-1",
        "title": "Software Engineer",
        "department_raw": "Engineering",
        "location": "SF",
        "work_mode": None,
        "employment_type": "full_time",
        "description": "Build stuff.",
        "url": "https://acme.com/jobs/1",
    }
    db.upsert_posting("acme", posting, "hash_v1", "2026-03-13")
    return db


class TestInitDb:
    def test_creates_tables(self, db: JobWatchDB):
        conn = db._connect()
        tables: list[dict] = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        table_names: set[str] = {t["name"] for t in tables}
        assert "companies" in table_names
        assert "crawl_runs" in table_names
        assert "postings" in table_names
        assert "classifications" in table_names
        assert "snapshots" in table_names


class TestCompanyAndCrawlRun:
    def test_ensure_company_idempotent(self, db: JobWatchDB):
        db.ensure_company("acme", "Acme Corp", "greenhouse", "acme", None)
        db.ensure_company("acme", "Acme Corp", "greenhouse", "acme", None)
        conn = db._connect()
        rows: list[dict] = conn.execute("SELECT * FROM companies").fetchall()
        assert len(rows) == 1

    def test_create_crawl_run_returns_id(self, db: JobWatchDB):
        db.ensure_company("acme", "Acme Corp", "greenhouse", "acme", None)
        run_id: int = db.create_crawl_run("acme", "2026-03-13T00:00:00Z")
        assert isinstance(run_id, int)
        assert run_id > 0

    def test_update_crawl_run(self, db: JobWatchDB):
        db.ensure_company("acme", "Acme Corp", "greenhouse", "acme", None)
        run_id: int = db.create_crawl_run("acme", "2026-03-13T00:00:00Z")
        db.update_crawl_run(
            run_id,
            status="complete",
            postings_found=10,
            finished_at="2026-03-13T00:01:00Z",
        )
        conn = db._connect()
        row: dict = conn.execute(
            "SELECT * FROM crawl_runs WHERE id = ?", (run_id,)
        ).fetchone()
        assert row["status"] == "complete"
        assert row["postings_found"] == 10
        assert row["finished_at"] == "2026-03-13T00:01:00Z"


class TestUpsertPosting:
    def test_new_insert(self, db: JobWatchDB):
        db.ensure_company("acme", "Acme Corp", "greenhouse", "acme", None)
        posting: dict = {
            "ats_job_id": "job-1",
            "title": "Engineer",
            "department_raw": "Eng",
            "location": "SF",
            "work_mode": None,
            "employment_type": "full_time",
            "description": "Build things.",
            "url": "https://acme.com/job-1",
        }
        pid: str
        is_new: bool
        changed: bool
        pid, is_new, changed = db.upsert_posting("acme", posting, "hash1", "2026-03-13")
        assert pid == "acme:job-1"
        assert is_new is True
        assert changed is False

    def test_unchanged_returns_false_false(self, seeded_db: JobWatchDB):
        posting: dict = {
            "ats_job_id": "job-1",
            "title": "Software Engineer",
            "department_raw": "Engineering",
            "location": "SF",
            "work_mode": None,
            "employment_type": "full_time",
            "description": "Build stuff.",
            "url": "https://acme.com/jobs/1",
        }
        pid: str
        is_new: bool
        changed: bool
        pid, is_new, changed = seeded_db.upsert_posting(
            "acme", posting, "hash_v1", "2026-03-14"
        )
        assert pid == "acme:job-1"
        assert is_new is False
        assert changed is False

    def test_content_change_detected(self, seeded_db: JobWatchDB):
        posting: dict = {
            "ats_job_id": "job-1",
            "title": "Senior Software Engineer",
            "department_raw": "Engineering",
            "location": "SF",
            "work_mode": None,
            "employment_type": "full_time",
            "description": "Build stuff, now senior.",
            "url": "https://acme.com/jobs/1",
        }
        pid: str
        is_new: bool
        changed: bool
        pid, is_new, changed = seeded_db.upsert_posting(
            "acme", posting, "hash_v2", "2026-03-14"
        )
        assert pid == "acme:job-1"
        assert is_new is False
        assert changed is True


class TestClosePosting:
    def test_close_marks_inactive(self, seeded_db: JobWatchDB):
        seeded_db.close_posting("acme:job-1", "2026-03-14T00:00:00Z")
        active: dict[str, dict] = seeded_db.get_active_postings("acme")
        assert len(active) == 0


class TestClassifications:
    def test_insert_and_has_current(self, seeded_db: JobWatchDB):
        classification: dict = {
            "justification": "Title says engineer.",
            "department": "ENG",
            "role_type": "ENG.GEN",
            "seniority": "MID",
            "confidence": 0.9,
        }
        seeded_db.insert_classification(
            "acme:job-1", classification, "haiku", "v1", "v1", "new_posting"
        )
        has: bool = seeded_db.has_current_classification(
            "acme:job-1", "hash_v1", "v1", "v1"
        )
        assert has is True

    def test_has_current_false_wrong_hash(self, seeded_db: JobWatchDB):
        classification: dict = {
            "justification": "Title says engineer.",
            "department": "ENG",
            "role_type": "ENG.GEN",
            "seniority": "MID",
            "confidence": 0.9,
        }
        seeded_db.insert_classification(
            "acme:job-1", classification, "haiku", "v1", "v1", "new_posting"
        )
        has: bool = seeded_db.has_current_classification(
            "acme:job-1", "different_hash", "v1", "v1"
        )
        assert has is False

    def test_new_classification_retires_previous(self, seeded_db: JobWatchDB):
        first: dict = {
            "justification": "First pass.",
            "department": "ENG",
            "role_type": "ENG.GEN",
            "seniority": "MID",
            "confidence": 0.7,
        }
        second: dict = {
            "justification": "Revised.",
            "department": "ENG",
            "role_type": "ENG.BE",
            "seniority": "SENIOR",
            "confidence": 0.95,
        }
        seeded_db.insert_classification(
            "acme:job-1", first, "haiku", "v1", "v1", "new_posting"
        )
        seeded_db.insert_classification(
            "acme:job-1", second, "haiku", "v1", "v1", "content_change"
        )
        conn = seeded_db._connect()
        current: list[dict] = conn.execute(
            "SELECT * FROM classifications WHERE posting_id = ? AND is_current = 1",
            ("acme:job-1",),
        ).fetchall()
        all_rows: list[dict] = conn.execute(
            "SELECT * FROM classifications WHERE posting_id = ?",
            ("acme:job-1",),
        ).fetchall()
        assert len(current) == 1
        assert current[0]["role_type"] == "ENG.BE"
        assert len(all_rows) == 2


class TestSnapshots:
    def test_insert_and_get(self, db: JobWatchDB):
        db.ensure_company("acme", "Acme Corp", "greenhouse", "acme", None)
        run_id: int = db.create_crawl_run("acme", "2026-03-13T00:00:00Z")
        dept: dict = {"ENG": 5, "PROD": 2}
        role: dict = {"ENG.BE": 3, "ENG.FE": 2, "PROD.GEN": 2}
        seniority: dict = {"SENIOR": 4, "MID": 3}
        db.insert_snapshot(
            "acme", run_id, "2026-03-13", 7, dept, role, seniority, 3, 1
        )
        snapshots: list[dict] = db.get_snapshots("acme")
        assert len(snapshots) == 1
        snap: dict = snapshots[0]
        assert snap["total_active"] == 7
        assert snap["dept_counts"] == dept
        assert snap["role_type_counts"] == role
        assert snap["seniority_counts"] == seniority
        assert snap["new_postings"] == 3
        assert snap["closed_postings"] == 1

    def test_get_snapshots_all(self, db: JobWatchDB):
        db.ensure_company("acme", "Acme Corp", "greenhouse", "acme", None)
        db.ensure_company("beta", "Beta Inc", "ashby", "beta", None)
        run1: int = db.create_crawl_run("acme", "2026-03-13T00:00:00Z")
        run2: int = db.create_crawl_run("beta", "2026-03-13T00:00:00Z")
        db.insert_snapshot("acme", run1, "2026-03-13", 5, {}, {}, {}, 5, 0)
        db.insert_snapshot("beta", run2, "2026-03-13", 3, {}, {}, {}, 3, 0)
        all_snaps: list[dict] = db.get_snapshots()
        assert len(all_snaps) == 2


class TestDepartmentMix:
    def test_counts_active_only(self, seeded_db: JobWatchDB):
        classification: dict = {
            "justification": "Engineer role.",
            "department": "ENG",
            "role_type": "ENG.GEN",
            "seniority": "MID",
            "confidence": 0.9,
        }
        seeded_db.insert_classification(
            "acme:job-1", classification, "haiku", "v1", "v1", "new_posting"
        )
        mix: list[dict] = seeded_db.get_department_mix("acme")
        assert len(mix) == 1
        assert mix[0]["department"] == "ENG"
        assert mix[0]["count"] == 1


class TestGetLowConfidence:
    def test_returns_below_threshold(self, seeded_db: JobWatchDB):
        classification: dict = {
            "justification": "Uncertain.",
            "department": "UNKNOWN",
            "role_type": "UNKNOWN.GEN",
            "seniority": "UNKNOWN",
            "confidence": 0.4,
        }
        seeded_db.insert_classification(
            "acme:job-1", classification, "haiku", "v1", "v1", "new_posting"
        )
        low: list[dict] = seeded_db.get_low_confidence(threshold=0.6)
        assert len(low) == 1
        assert low[0]["confidence"] == 0.4

    def test_excludes_above_threshold(self, seeded_db: JobWatchDB):
        classification: dict = {
            "justification": "Confident.",
            "department": "ENG",
            "role_type": "ENG.BE",
            "seniority": "SENIOR",
            "confidence": 0.95,
        }
        seeded_db.insert_classification(
            "acme:job-1", classification, "haiku", "v1", "v1", "new_posting"
        )
        low: list[dict] = seeded_db.get_low_confidence(threshold=0.6)
        assert len(low) == 0
