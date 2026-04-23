"""V2 JSONL evidence ledger — one logical source per line."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from harness.workflows.evidence.paths import CompanyPaths

LEDGER_VERSION = 2
EVIDENCE_STATUSES: frozenset[str] = frozenset({"downloaded", "discovered", "blocked"})


def make_evidence_id(
    *,
    ticker: str,
    category: str,
    title: str,
    local_path: str | None,
    url: str | None,
) -> str:
    """Deterministic 12-char hex: sha1(ticker|category|title|local_path|url)[:12]."""
    payload = "|".join([ticker.upper(), category, title, local_path or "", url or ""])
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def load_ledger(paths: CompanyPaths) -> list[dict[str, Any]]:
    """Return the ledger as a list of dicts. Empty list when missing."""
    path = paths.evidence_jsonl
    if not path.exists():
        return []
    entries: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        entries.append(json.loads(stripped))
    return entries


def upsert_evidence(
    paths: CompanyPaths,
    *,
    ticker: str,
    category: str,
    status: str,
    title: str,
    local_path: str | None,
    url: str | None,
    date: str | None,
    notes: str | None,
    collector: str | None,
) -> dict[str, Any]:
    """Placeholder — implemented in Task 1.3."""
    raise NotImplementedError("upsert_evidence not yet implemented")
