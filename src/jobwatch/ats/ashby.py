"""Ashby ATS client (Cursor, Cognition)."""

from __future__ import annotations

import hashlib

import httpx

from jobwatch.ats._utils import normalize_employment_type, strip_html
from jobwatch.ats.base import ATSClient
from jobwatch.models import FetchResult, RawPosting


class AshbyClient(ATSClient):
    """Fetch jobs from the Ashby posting API."""

    _BASE_URL: str = "https://api.ashbyhq.com/posting-api/job-board"

    def fetch_all(self) -> FetchResult:
        url: str = f"{self._BASE_URL}/{self.board_slug}"
        resp: httpx.Response = httpx.get(url, timeout=30)
        if resp.status_code != 200:
            raise RuntimeError(
                f"Ashby API returned {resp.status_code} for board "
                f"'{self.board_slug}': {resp.text[:300]}"
            )

        raw_body: bytes = resp.content
        response_hash: str = hashlib.sha256(raw_body).hexdigest()

        data: dict = resp.json()
        jobs: list[dict] = data.get("jobs", [])

        postings: list[RawPosting] = []
        for job in jobs:
            description_plain: str | None = job.get("descriptionPlain")
            description_html: str | None = job.get("descriptionHtml")
            description: str | None = (
                description_plain
                if description_plain
                else (strip_html(description_html) if description_html else None)
            )

            job_url: str | None = job.get("jobUrl") or (
                f"https://jobs.ashbyhq.com/{self.board_slug}/{job['id']}"
            )

            posting = RawPosting(
                ats_job_id=str(job["id"]),
                title=job["title"],
                department_raw=job.get("departmentName"),
                location=job.get("location"),
                employment_type=normalize_employment_type(job.get("employmentType")),
                description=description,
                url=job_url,
            )
            postings.append(posting)

        return FetchResult(
            postings=postings,
            is_exhaustive=True,
            response_hash=response_hash,
        )
