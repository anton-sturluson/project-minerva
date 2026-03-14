"""Tests for Ashby SSR client."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from jobwatch.ats.ashby_ssr import AshbySSRClient
from jobwatch.models import FetchResult, RawPosting

FIXTURES_DIR: Path = Path(__file__).parent / "fixtures"


@pytest.fixture
def ssr_html() -> str:
    return (FIXTURES_DIR / "openai_ssr.html").read_text()


@pytest.fixture
def mock_response(ssr_html: str) -> MagicMock:
    resp: MagicMock = MagicMock()
    resp.status_code = 200
    resp.text = ssr_html
    resp.content = ssr_html.encode()
    return resp


class TestAshbySSRClient:
    def test_extracts_app_data(self, mock_response: MagicMock):
        with patch("jobwatch.ats.ashby_ssr.httpx.get", return_value=mock_response):
            client: AshbySSRClient = AshbySSRClient("openai")
            result: FetchResult = client.fetch_all()

        assert len(result.postings) == 2

    def test_field_mapping(self, mock_response: MagicMock):
        with patch("jobwatch.ats.ashby_ssr.httpx.get", return_value=mock_response):
            client: AshbySSRClient = AshbySSRClient("openai")
            result: FetchResult = client.fetch_all()

        first: RawPosting = result.postings[0]
        assert first.ats_job_id == "post-001"
        assert first.title == "Applied AI Engineer"
        assert first.department_raw == "Applied AI"
        assert first.location == "San Francisco"
        assert first.employment_type == "full_time"
        assert first.url == "https://jobs.ashbyhq.com/openai/post-001"

    def test_html_stripped_from_description(self, mock_response: MagicMock):
        with patch("jobwatch.ats.ashby_ssr.httpx.get", return_value=mock_response):
            client: AshbySSRClient = AshbySSRClient("openai")
            result: FetchResult = client.fetch_all()

        for posting in result.postings:
            assert posting.description is not None
            assert "<p>" not in posting.description

    def test_response_hash_computed(self, mock_response: MagicMock):
        with patch("jobwatch.ats.ashby_ssr.httpx.get", return_value=mock_response):
            client: AshbySSRClient = AshbySSRClient("openai")
            result: FetchResult = client.fetch_all()

        assert isinstance(result.response_hash, str)
        assert len(result.response_hash) == 64

    def test_is_exhaustive_true(self, mock_response: MagicMock):
        with patch("jobwatch.ats.ashby_ssr.httpx.get", return_value=mock_response):
            client: AshbySSRClient = AshbySSRClient("openai")
            result: FetchResult = client.fetch_all()

        assert result.is_exhaustive is True

    def test_no_app_data_raises(self):
        resp: MagicMock = MagicMock()
        resp.status_code = 200
        resp.text = "<html><body><p>No jobs here</p></body></html>"
        resp.content = resp.text.encode()

        with patch("jobwatch.ats.ashby_ssr.httpx.get", return_value=resp):
            client: AshbySSRClient = AshbySSRClient("openai")
            with pytest.raises(RuntimeError, match="Could not find window.__appData"):
                client.fetch_all()

    def test_non_200_raises(self):
        resp: MagicMock = MagicMock()
        resp.status_code = 403
        resp.text = "Forbidden"

        with patch("jobwatch.ats.ashby_ssr.httpx.get", return_value=resp):
            client: AshbySSRClient = AshbySSRClient("openai")
            with pytest.raises(RuntimeError, match="Ashby SSR returned 403"):
                client.fetch_all()

    def test_second_posting_fields(self, mock_response: MagicMock):
        with patch("jobwatch.ats.ashby_ssr.httpx.get", return_value=mock_response):
            client: AshbySSRClient = AshbySSRClient("openai")
            result: FetchResult = client.fetch_all()

        second: RawPosting = result.postings[1]
        assert second.ats_job_id == "post-002"
        assert second.title == "Research Scientist, Reasoning"
        assert second.department_raw == "Research"
