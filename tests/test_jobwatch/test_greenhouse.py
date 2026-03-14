"""Tests for Greenhouse ATS client."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from jobwatch.ats.greenhouse import GreenhouseClient, _strip_html
from jobwatch.models import FetchResult, RawPosting

FIXTURES_DIR: Path = Path(__file__).parent / "fixtures"


@pytest.fixture
def greenhouse_json() -> dict:
    raw: str = (FIXTURES_DIR / "greenhouse_anthropic.json").read_text()
    return json.loads(raw)


@pytest.fixture
def mock_response(greenhouse_json: dict) -> MagicMock:
    body: bytes = json.dumps(greenhouse_json).encode()
    resp: MagicMock = MagicMock()
    resp.status_code = 200
    resp.content = body
    resp.json.return_value = greenhouse_json
    return resp


class TestStripHtml:
    def test_removes_tags(self):
        assert _strip_html("<p>hello</p>") == "hello"

    def test_strips_whitespace(self):
        assert _strip_html("  <b>hi</b>  ") == "hi"

    def test_nested_tags(self):
        assert _strip_html("<ul><li>a</li><li>b</li></ul>") == "ab"


class TestGreenhouseClient:
    def test_fetch_all_returns_correct_count(
        self, mock_response: MagicMock
    ):
        with patch("jobwatch.ats.greenhouse.httpx.get", return_value=mock_response):
            client: GreenhouseClient = GreenhouseClient("anthropic")
            result: FetchResult = client.fetch_all()

        assert len(result.postings) == 3

    def test_field_mapping(self, mock_response: MagicMock):
        with patch("jobwatch.ats.greenhouse.httpx.get", return_value=mock_response):
            client: GreenhouseClient = GreenhouseClient("anthropic")
            result: FetchResult = client.fetch_all()

        first: RawPosting = result.postings[0]
        assert first.ats_job_id == "5678901"
        assert first.title == "Senior Software Engineer, API Platform"
        assert first.department_raw == "Engineering"
        assert first.location == "San Francisco, CA"
        assert first.url == "https://boards.greenhouse.io/anthropic/jobs/5678901"

    def test_html_stripped_from_description(self, mock_response: MagicMock):
        with patch("jobwatch.ats.greenhouse.httpx.get", return_value=mock_response):
            client: GreenhouseClient = GreenhouseClient("anthropic")
            result: FetchResult = client.fetch_all()

        for posting in result.postings:
            assert posting.description is not None
            assert "<p>" not in posting.description
            assert "<ul>" not in posting.description
            assert "<li>" not in posting.description

    def test_response_hash_computed(self, mock_response: MagicMock):
        with patch("jobwatch.ats.greenhouse.httpx.get", return_value=mock_response):
            client: GreenhouseClient = GreenhouseClient("anthropic")
            result: FetchResult = client.fetch_all()

        assert isinstance(result.response_hash, str)
        assert len(result.response_hash) == 64

    def test_is_exhaustive_true(self, mock_response: MagicMock):
        with patch("jobwatch.ats.greenhouse.httpx.get", return_value=mock_response):
            client: GreenhouseClient = GreenhouseClient("anthropic")
            result: FetchResult = client.fetch_all()

        assert result.is_exhaustive is True

    def test_department_join_multiple(self, mock_response: MagicMock, greenhouse_json: dict):
        greenhouse_json["jobs"][0]["departments"] = [
            {"id": 1, "name": "Engineering"},
            {"id": 2, "name": "Platform"},
        ]
        body: bytes = json.dumps(greenhouse_json).encode()
        mock_response.content = body
        mock_response.json.return_value = greenhouse_json

        with patch("jobwatch.ats.greenhouse.httpx.get", return_value=mock_response):
            client: GreenhouseClient = GreenhouseClient("anthropic")
            result: FetchResult = client.fetch_all()

        assert result.postings[0].department_raw == "Engineering, Platform"

    def test_non_200_raises(self):
        error_resp: MagicMock = MagicMock()
        error_resp.status_code = 404
        error_resp.text = "Not Found"

        with patch("jobwatch.ats.greenhouse.httpx.get", return_value=error_resp):
            client: GreenhouseClient = GreenhouseClient("badboard")
            with pytest.raises(RuntimeError, match="Greenhouse API returned 404"):
                client.fetch_all()
