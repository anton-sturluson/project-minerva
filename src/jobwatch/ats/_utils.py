"""Shared utilities for ATS clients."""

from __future__ import annotations

import re

_HTML_TAG_RE: re.Pattern[str] = re.compile(r"<[^>]+>")

_EMPLOYMENT_TYPE_MAP: dict[str, str] = {
    "fulltime": "full_time",
    "full-time": "full_time",
    "full_time": "full_time",
    "parttime": "part_time",
    "part-time": "part_time",
    "part_time": "part_time",
    "contract": "contract",
    "contractor": "contract",
    "intern": "intern",
    "internship": "intern",
}


def strip_html(html: str) -> str:
    """Remove HTML tags and trim whitespace."""
    return _HTML_TAG_RE.sub("", html).strip()


def normalize_employment_type(raw: str | None) -> str | None:
    """Normalize employment type string to canonical form."""
    if raw is None:
        return None
    return _EMPLOYMENT_TYPE_MAP.get(raw.lower().strip())
