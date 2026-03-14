"""Ashby SSR client (OpenAI) — scrapes window.__appData from server-rendered HTML.

WARNING: This is a brittle integration. Ashby may change their SSR HTML
structure or __appData schema without notice, breaking this client.
"""

from __future__ import annotations

import hashlib
import json
import re

import httpx

from jobwatch.ats._utils import normalize_employment_type, strip_html
from jobwatch.ats.base import ATSClient
from jobwatch.models import FetchResult, RawPosting

_APP_DATA_MARKER: re.Pattern[str] = re.compile(
    r"window\.__appData\s*=\s*"
)


class AshbySSRClient(ATSClient):
    """Scrape job postings from Ashby's server-rendered job board page.

    Extracts the ``window.__appData`` JSON blob embedded in the HTML.
    This is brittle — Ashby may change the page structure at any time.
    """

    _BASE_URL: str = "https://jobs.ashbyhq.com"

    def fetch_all(self) -> FetchResult:
        url: str = f"{self._BASE_URL}/{self.board_slug}"
        resp: httpx.Response = httpx.get(url, timeout=30)
        if resp.status_code != 200:
            raise RuntimeError(
                f"Ashby SSR returned {resp.status_code} for board "
                f"'{self.board_slug}': {resp.text[:300]}"
            )

        raw_html: str = resp.text
        response_hash: str = hashlib.sha256(resp.content).hexdigest()

        marker: re.Match[str] | None = _APP_DATA_MARKER.search(raw_html)
        if marker is None:
            raise RuntimeError(
                f"Could not find window.__appData in Ashby SSR page for "
                f"board '{self.board_slug}'. The page structure may have changed."
            )

        decoder: json.JSONDecoder = json.JSONDecoder()
        app_data: dict
        try:
            app_data, _ = decoder.raw_decode(raw_html, marker.end())
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"Failed to parse window.__appData JSON for board "
                f"'{self.board_slug}': {exc}"
            ) from exc
        job_board: dict = app_data.get("jobBoard", {})
        job_list: list[dict] = job_board.get("jobPostings", [])

        postings: list[RawPosting] = []
        for job in job_list:
            job_id: str = str(job["id"])
            desc_html: str | None = job.get("descriptionHtml")
            description: str | None = (
                strip_html(desc_html) if desc_html else None
            )

            posting = RawPosting(
                ats_job_id=job_id,
                title=job["title"],
                department_raw=job.get("departmentName"),
                location=job.get("locationName"),
                employment_type=normalize_employment_type(job.get("employmentType")),
                description=description,
                url=f"{self._BASE_URL}/{self.board_slug}/{job_id}",
            )
            postings.append(posting)

        return FetchResult(
            postings=postings,
            is_exhaustive=True,
            response_hash=response_hash,
        )
