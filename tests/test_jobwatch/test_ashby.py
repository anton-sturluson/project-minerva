"""Tests for Ashby ATS client."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from jobwatch.ats._utils import normalize_employment_type
from jobwatch.ats.ashby import AshbyClient
from jobwatch.models import FetchResult, RawPosting

FIXTURES_DIR: Path = Path(__file__).parent / "fixtures"


@pytest.fixture
def ashby_json() -> dict:
    raw: str = (FIXTURES_DIR / "ashby_cursor.json").read_text()
    return json.loads(raw)


@pytest.fixture
def mock_response(ashby_json: dict) -> MagicMock:
    body: bytes = json.dumps(ashby_json).encode()
    resp: MagicMock = MagicMock()
    resp.status_code = 200
    resp.content = body
    resp.json.return_value = ashby_json
    return resp


class TestNormalizeEmploymentType:
    def test_fulltime_variants(self):
        assert normalize_employment_type("FullTime") == "full_time"
        assert normalize_employment_type("fulltime") == "full_time"
        assert normalize_employment_type("full-time") == "full_time"
        assert normalize_employment_type("full_time") == "full_time"

    def test_parttime_variants(self):
        assert normalize_employment_type("PartTime") == "part_time"
        assert normalize_employment_type("parttime") == "part_time"
        assert normalize_employment_type("part-time") == "part_time"

    def test_contract_variants(self):
        assert normalize_employment_type("contract") == "contract"
        assert normalize_employment_type("contractor") == "contract"

    def test_intern_variants(self):
        assert normalize_employment_type("intern") == "intern"
        assert normalize_employment_type("internship") == "intern"

    def test_none_passthrough(self):
        assert normalize_employment_type(None) is None

    def test_unknown_returns_none(self):
        assert normalize_employment_type("Freelance") is None


class TestAshbyClient:
    def test_fetch_all_returns_correct_count(self, mock_response: MagicMock):
        with patch("jobwatch.ats.ashby.httpx.get", return_value=mock_response):
            client: AshbyClient = AshbyClient("cursor")
            result: FetchResult = client.fetch_all()

        assert len(result.postings) == 2

    def test_field_mapping(self, mock_response: MagicMock):
        with patch("jobwatch.ats.ashby.httpx.get", return_value=mock_response):
            client: AshbyClient = AshbyClient("cursor")
            result: FetchResult = client.fetch_all()

        first: RawPosting = result.postings[0]
        assert first.ats_job_id == "abc-123-def"
        assert first.title == "Full-Stack Engineer"
        assert first.department_raw == "Engineering"
        assert first.location == "San Francisco, CA"
        assert first.url == "https://jobs.ashbyhq.com/cursor/abc-123-def"

    def test_employment_type_normalized(self, mock_response: MagicMock):
        with patch("jobwatch.ats.ashby.httpx.get", return_value=mock_response):
            client: AshbyClient = AshbyClient("cursor")
            result: FetchResult = client.fetch_all()

        for posting in result.postings:
            assert posting.employment_type == "full_time"

    def test_description_from_plain_text(self, mock_response: MagicMock):
        with patch("jobwatch.ats.ashby.httpx.get", return_value=mock_response):
            client: AshbyClient = AshbyClient("cursor")
            result: FetchResult = client.fetch_all()

        first: RawPosting = result.postings[0]
        assert first.description is not None
        assert "AI-powered code editing" in first.description

    def test_response_hash_computed(self, mock_response: MagicMock):
        with patch("jobwatch.ats.ashby.httpx.get", return_value=mock_response):
            client: AshbyClient = AshbyClient("cursor")
            result: FetchResult = client.fetch_all()

        assert isinstance(result.response_hash, str)
        assert len(result.response_hash) == 64

    def test_fallback_url_when_no_job_url(self, mock_response: MagicMock, ashby_json: dict):
        del ashby_json["jobs"][0]["jobUrl"]
        body: bytes = json.dumps(ashby_json).encode()
        mock_response.content = body
        mock_response.json.return_value = ashby_json

        with patch("jobwatch.ats.ashby.httpx.get", return_value=mock_response):
            client: AshbyClient = AshbyClient("cursor")
            result: FetchResult = client.fetch_all()

        assert result.postings[0].url == "https://jobs.ashbyhq.com/cursor/abc-123-def"

    def test_non_200_raises(self):
        error_resp: MagicMock = MagicMock()
        error_resp.status_code = 500
        error_resp.text = "Internal Server Error"

        with patch("jobwatch.ats.ashby.httpx.get", return_value=error_resp):
            client: AshbyClient = AshbyClient("badboard")
            with pytest.raises(RuntimeError, match="Ashby API returned 500"):
                client.fetch_all()
