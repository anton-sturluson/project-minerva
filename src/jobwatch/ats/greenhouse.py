"""Greenhouse ATS client (Anthropic, xAI)."""

from __future__ import annotations

import hashlib
import re

import httpx

from jobwatch.ats.base import ATSClient
from jobwatch.models import FetchResult, RawPosting

_HTML_TAG_RE: re.Pattern[str] = re.compile(r"<[^>]+>")


def _strip_html(html: str) -> str:
    return _HTML_TAG_RE.sub("", html).strip()


class GreenhouseClient(ATSClient):
    """Fetch jobs from Greenhouse boards API."""

    _BASE_URL: str = "https://boards-api.greenhouse.io/v1/boards"

    def fetch_all(self) -> FetchResult:
        url: str = f"{self._BASE_URL}/{self.board_slug}/jobs?content=true&per_page=500"
        resp: httpx.Response = httpx.get(url, timeout=30)
        if resp.status_code != 200:
            raise RuntimeError(
                f"Greenhouse API returned {resp.status_code} for board "
                f"'{self.board_slug}': {resp.text[:300]}"
            )

        raw_body: bytes = resp.content
        response_hash: str = hashlib.sha256(raw_body).hexdigest()

        data: dict = resp.json()
        jobs: list[dict] = data.get("jobs", [])

        postings: list[RawPosting] = []
        for job in jobs:
            departments: list[dict] = job.get("departments", [])
            dept_raw: str | None = (
                ", ".join(d["name"] for d in departments if d.get("name"))
                or None
            )
            location_obj: dict | None = job.get("location")
            location: str | None = (
                location_obj.get("name") if location_obj else None
            )
            content: str | None = job.get("content")
            description: str | None = _strip_html(content) if content else None

            posting = RawPosting(
                ats_job_id=str(job["id"]),
                title=job["title"],
                department_raw=dept_raw,
                location=location,
                description=description,
                url=job.get("absolute_url"),
            )
            postings.append(posting)

        return FetchResult(
            postings=postings,
            is_exhaustive=True,
            response_hash=response_hash,
        )
