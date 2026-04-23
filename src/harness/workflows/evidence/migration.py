"""One-shot migration of V1 source-registry.json → V2 evidence.jsonl."""

from __future__ import annotations

import json
from typing import Any

from harness.workflows.evidence.ledger import upsert_evidence
from harness.workflows.evidence.paths import CompanyPaths

# ---------------------------------------------------------------------------
# Category mapping: (bucket, source_kind) → V2 category
# ---------------------------------------------------------------------------

# Bucket-level defaults (applied when source_kind doesn't match finer rules).
_BUCKET_DEFAULTS: dict[str, str] = {
    "sec-filings-annual": "sec-annual",
    "sec-filings-quarterly": "sec-quarterly",
    "sec-earnings": "sec-earnings",
    "sec-filings-earnings": "sec-earnings",
    "sec-financials": "sec-financials",
    "sec-filings-financials": "sec-financials",
    "sec-proxy": "sec-proxy",
    "sec-other": "sec-other",
}

# source_kind-level overrides (checked before bucket fallback).
_KIND_OVERRIDES: dict[str, str] = {
    "sec-10k": "sec-annual",
    "sec-10q": "sec-quarterly",
    "sec-8k": "sec-earnings",
    "sec-proxy": "sec-proxy",
    "industry-report": "industry-report",
    "competitor-data": "competitor-data",
    "customer-evidence": "customer-evidence",
    "expert-input": "expert-input",
    "news": "news",
    "company-ir": "company-ir",
    "regulatory": "regulatory",
}


def _map_category(bucket: str, source_kind: str) -> str:
    """Return a V2 category for a V1 (bucket, source_kind) pair."""
    if source_kind in _KIND_OVERRIDES:
        return _KIND_OVERRIDES[source_kind]
    if bucket in _BUCKET_DEFAULTS:
        return _BUCKET_DEFAULTS[bucket]
    return "other"


def _is_html_or_csv(entry: dict[str, Any]) -> bool:
    """Return True if the entry is an HTML or CSV artefact that should be dropped."""
    source_kind: str = entry.get("source_kind") or ""
    local_path: str = entry.get("local_path") or ""
    if source_kind.endswith("-html") or local_path.endswith(".html"):
        return True
    if source_kind.endswith("-csv") or local_path.endswith(".csv"):
        return True
    return False


def migrate_v1_to_v2(paths: CompanyPaths) -> dict[str, int]:
    """Migrate ``source-registry.json`` to the V2 ``evidence.jsonl`` ledger.

    - Filters out HTML and CSV artefacts.
    - Maps ``(bucket, source_kind)`` to the appropriate V2 category.
    - Calls :func:`upsert_evidence` for each surviving entry (idempotent).
    - Renames ``source-registry.json`` → ``source-registry.archive.json``.
    - Returns ``{"migrated_count": N, "dropped_count": M}``.
    """
    registry_path = paths.source_registry_json
    archive_path = registry_path.parent / "source-registry.archive.json"

    # Idempotent: if already archived and registry is gone, skip gracefully.
    if not registry_path.exists() and archive_path.exists():
        return {"migrated_count": 0, "dropped_count": 0}

    # Load the V1 registry.
    payload: dict[str, Any] = json.loads(registry_path.read_text(encoding="utf-8"))
    ticker: str = (payload.get("ticker") or "UNKNOWN").upper()
    sources: list[dict[str, Any]] = payload.get("sources") or []

    migrated_count = 0
    dropped_count = 0

    for source in sources:
        if _is_html_or_csv(source):
            dropped_count += 1
            continue

        bucket: str = source.get("bucket") or ""
        source_kind: str = source.get("source_kind") or ""
        category = _map_category(bucket, source_kind)

        upsert_evidence(
            paths,
            ticker=ticker,
            category=category,
            status=source.get("status") or "discovered",
            title=source.get("title") or source.get("id") or "untitled",
            local_path=source.get("local_path"),
            url=source.get("url"),
            date=None,
            notes=source.get("notes"),
            collector=source.get("collector") or "v1-migration",
        )
        migrated_count += 1

    # Archive the old registry.
    registry_path.rename(archive_path)

    return {"migrated_count": migrated_count, "dropped_count": dropped_count}
