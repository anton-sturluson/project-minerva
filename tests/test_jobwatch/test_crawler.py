"""Tests for crawl orchestrator."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from jobwatch.ats.ashby import AshbyClient
from jobwatch.ats.ashby_ssr import AshbySSRClient
from jobwatch.ats.greenhouse import GreenhouseClient
from jobwatch.classifier import ClassifierProvider
from jobwatch.config import CompanyConfig, Settings
from jobwatch.crawler import compute_content_hash, crawl_company, get_ats_client
from jobwatch.db import JobWatchDB
from jobwatch.models import (
    ATSType,
    FetchResult,
    JobClassification,
    RawPosting,
)


class FakeCrawlClassifier(ClassifierProvider):
    """Deterministic classifier for crawler tests."""

    @property
    def model_name(self) -> str:
        return "test-model"

    def classify(
        self,
        title: str,
        department_raw: str | None,
        description: str | None,
    ) -> JobClassification:
        return JobClassification(
            justification=f"Classified: {title}",
            department="ENG",
            role_type="ENG.GEN",
            seniority="MID",
            confidence=0.85,
        )


def _make_postings() -> list[RawPosting]:
    return [
        RawPosting(
            ats_job_id="j1",
            title="Backend Engineer",
            department_raw="Engineering",
            location="SF",
            description="Build APIs.",
            url="https://example.com/j1",
        ),
        RawPosting(
            ats_job_id="j2",
            title="Product Manager",
            department_raw="Product",
            location="NYC",
            description="Own roadmap.",
            url="https://example.com/j2",
        ),
    ]


def _make_fetch_result(
    postings: list[RawPosting] | None = None, is_exhaustive: bool = True
) -> FetchResult:
    posts: list[RawPosting] = postings if postings is not None else _make_postings()
    return FetchResult(
        postings=posts, is_exhaustive=is_exhaustive, response_hash="abc123"
    )


def _make_company() -> CompanyConfig:
    return CompanyConfig(
        id="testco",
        name="Test Co",
        ats_type=ATSType.GREENHOUSE,
        ats_board="testco",
        website="https://testco.com",
    )


def _make_db(tmp_path: Path) -> JobWatchDB:
    db_path: Path = tmp_path / "crawl_test.db"
    db: JobWatchDB = JobWatchDB(db_path)
    db.init_db()
    return db


class TestComputeContentHash:
    def test_deterministic(self):
        h1: str = compute_content_hash("Engineer", "Build things.")
        h2: str = compute_content_hash("Engineer", "Build things.")
        assert h1 == h2

    def test_different_input_different_hash(self):
        h1: str = compute_content_hash("Engineer", "Build things.")
        h2: str = compute_content_hash("Engineer", "Build OTHER things.")
        assert h1 != h2

    def test_none_description(self):
        h1: str = compute_content_hash("Engineer", None)
        h2: str = compute_content_hash("Engineer", None)
        assert h1 == h2

    def test_sha256_length(self):
        h: str = compute_content_hash("Title", "Desc")
        assert len(h) == 64


class TestGetAtsClient:
    def test_greenhouse(self):
        company: CompanyConfig = CompanyConfig(
            id="a", name="A", ats_type=ATSType.GREENHOUSE, ats_board="a"
        )
        client = get_ats_client(company)
        assert isinstance(client, GreenhouseClient)
        assert client.board_slug == "a"

    def test_ashby(self):
        company: CompanyConfig = CompanyConfig(
            id="b", name="B", ats_type=ATSType.ASHBY, ats_board="b"
        )
        client = get_ats_client(company)
        assert isinstance(client, AshbyClient)

    def test_ashby_ssr(self):
        company: CompanyConfig = CompanyConfig(
            id="c", name="C", ats_type=ATSType.ASHBY_SSR, ats_board="c"
        )
        client = get_ats_client(company)
        assert isinstance(client, AshbySSRClient)


class TestCrawlCompanyFull:
    def test_postings_inserted_and_classified(self, tmp_path: Path):
        db: JobWatchDB = _make_db(tmp_path)
        company: CompanyConfig = _make_company()
        classifier: FakeCrawlClassifier = FakeCrawlClassifier()
        settings: Settings = Settings(
            db_path=tmp_path / "crawl_test.db",
            taxonomy_version="v1",
            prompt_version="v1",
        )
        fetch_result: FetchResult = _make_fetch_result()
        fake_client: MagicMock = MagicMock()
        fake_client.fetch_all.return_value = fetch_result

        with patch("jobwatch.crawler.get_ats_client", return_value=fake_client):
            summary: dict = crawl_company(db, company, classifier, settings)

        assert summary["postings_found"] == 2
        assert summary["new"] == 2
        assert summary["classified"] == 2
        assert summary["status"] == "complete"

        active: dict[str, dict] = db.get_active_postings("testco")
        assert len(active) == 2

    def test_crawl_run_updated(self, tmp_path: Path):
        db: JobWatchDB = _make_db(tmp_path)
        company: CompanyConfig = _make_company()
        classifier: FakeCrawlClassifier = FakeCrawlClassifier()
        settings: Settings = Settings(
            db_path=tmp_path / "crawl_test.db",
            taxonomy_version="v1",
            prompt_version="v1",
        )
        fake_client: MagicMock = MagicMock()
        fake_client.fetch_all.return_value = _make_fetch_result()

        with patch("jobwatch.crawler.get_ats_client", return_value=fake_client):
            crawl_company(db, company, classifier, settings)

        runs: list[dict] = db.get_recent_crawl_runs(limit=1)
        assert len(runs) == 1
        assert runs[0]["status"] == "complete"
        assert runs[0]["postings_found"] == 2

    def test_snapshot_created(self, tmp_path: Path):
        db: JobWatchDB = _make_db(tmp_path)
        company: CompanyConfig = _make_company()
        classifier: FakeCrawlClassifier = FakeCrawlClassifier()
        settings: Settings = Settings(
            db_path=tmp_path / "crawl_test.db",
            taxonomy_version="v1",
            prompt_version="v1",
        )
        fake_client: MagicMock = MagicMock()
        fake_client.fetch_all.return_value = _make_fetch_result()

        with patch("jobwatch.crawler.get_ats_client", return_value=fake_client):
            crawl_company(db, company, classifier, settings)

        snapshots: list[dict] = db.get_snapshots("testco")
        assert len(snapshots) == 1
        assert snapshots[0]["total_active"] == 2
        assert snapshots[0]["new_postings"] == 2


class TestClosureSafety:
    def test_partial_crawl_does_not_close(self, tmp_path: Path):
        """Non-exhaustive crawl should not close missing postings."""
        db: JobWatchDB = _make_db(tmp_path)
        company: CompanyConfig = _make_company()
        classifier: FakeCrawlClassifier = FakeCrawlClassifier()
        settings: Settings = Settings(
            db_path=tmp_path / "crawl_test.db",
            taxonomy_version="v1",
            prompt_version="v1",
        )

        full_postings: list[RawPosting] = _make_postings()
        fake_client_full: MagicMock = MagicMock()
        fake_client_full.fetch_all.return_value = _make_fetch_result(
            full_postings, is_exhaustive=True
        )
        with patch("jobwatch.crawler.get_ats_client", return_value=fake_client_full):
            crawl_company(db, company, classifier, settings)

        assert len(db.get_active_postings("testco")) == 2

        partial_postings: list[RawPosting] = [full_postings[0]]
        fake_client_partial: MagicMock = MagicMock()
        fake_client_partial.fetch_all.return_value = _make_fetch_result(
            partial_postings, is_exhaustive=False
        )
        with patch("jobwatch.crawler.get_ats_client", return_value=fake_client_partial):
            summary: dict = crawl_company(db, company, classifier, settings)

        assert summary["closed"] == 0
        assert len(db.get_active_postings("testco")) == 2

    def test_exhaustive_crawl_closes_missing(self, tmp_path: Path):
        """Exhaustive crawl with missing posting should close it."""
        db: JobWatchDB = _make_db(tmp_path)
        company: CompanyConfig = _make_company()
        classifier: FakeCrawlClassifier = FakeCrawlClassifier()
        settings: Settings = Settings(
            db_path=tmp_path / "crawl_test.db",
            taxonomy_version="v1",
            prompt_version="v1",
        )

        day1: datetime = datetime(2026, 3, 13, tzinfo=timezone.utc)
        full_postings: list[RawPosting] = _make_postings()
        fake_client: MagicMock = MagicMock()
        fake_client.fetch_all.return_value = _make_fetch_result(
            full_postings, is_exhaustive=True
        )
        with (
            patch("jobwatch.crawler.get_ats_client", return_value=fake_client),
            patch("jobwatch.crawler.datetime") as mock_dt,
        ):
            mock_dt.now.return_value = day1
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            crawl_company(db, company, classifier, settings)

        day2: datetime = datetime(2026, 3, 14, tzinfo=timezone.utc)
        reduced: list[RawPosting] = [full_postings[0]]
        fake_client2: MagicMock = MagicMock()
        fake_client2.fetch_all.return_value = _make_fetch_result(
            reduced, is_exhaustive=True
        )
        with (
            patch("jobwatch.crawler.get_ats_client", return_value=fake_client2),
            patch("jobwatch.crawler.datetime") as mock_dt2,
        ):
            mock_dt2.now.return_value = day2
            mock_dt2.side_effect = lambda *a, **kw: datetime(*a, **kw)
            summary: dict = crawl_company(db, company, classifier, settings)

        assert summary["closed"] == 1
        active: dict[str, dict] = db.get_active_postings("testco")
        assert len(active) == 1
        assert "testco:j1" in active


class TestIdempotency:
    def test_second_crawl_skips_classification(self, tmp_path: Path):
        """Running the same crawl twice should not re-classify unchanged postings."""
        db: JobWatchDB = _make_db(tmp_path)
        company: CompanyConfig = _make_company()
        classifier: FakeCrawlClassifier = FakeCrawlClassifier()
        settings: Settings = Settings(
            db_path=tmp_path / "crawl_test.db",
            taxonomy_version="v1",
            prompt_version="v1",
        )

        day1: datetime = datetime(2026, 3, 13, tzinfo=timezone.utc)
        fake_client: MagicMock = MagicMock()
        fake_client.fetch_all.return_value = _make_fetch_result()

        with (
            patch("jobwatch.crawler.get_ats_client", return_value=fake_client),
            patch("jobwatch.crawler.datetime") as mock_dt,
        ):
            mock_dt.now.return_value = day1
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            first: dict = crawl_company(db, company, classifier, settings)

        assert first["classified"] == 2

        day2: datetime = datetime(2026, 3, 14, tzinfo=timezone.utc)
        fake_client2: MagicMock = MagicMock()
        fake_client2.fetch_all.return_value = _make_fetch_result()

        with (
            patch("jobwatch.crawler.get_ats_client", return_value=fake_client2),
            patch("jobwatch.crawler.datetime") as mock_dt2,
        ):
            mock_dt2.now.return_value = day2
            mock_dt2.side_effect = lambda *a, **kw: datetime(*a, **kw)
            second: dict = crawl_company(db, company, classifier, settings)

        assert second["new"] == 0
        assert second["changed"] == 0
        assert second["classified"] == 0
        assert second["unchanged"] == 2
