"""Registry state and company-tree helpers."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from harness.workflows.evidence.paths import CompanyPaths
from harness.workflows.evidence.render import refresh_indexes, render_source_registry_markdown, write_json

SOURCE_STATUSES: frozenset[str] = frozenset({"downloaded", "discovered", "blocked"})


def ensure_company_tree(paths: CompanyPaths) -> None:
    """Create the canonical company evidence tree."""
    for directory in [
        paths.root,
        paths.notes_dir,
        paths.sources_dir,
        paths.references_dir,
        paths.structured_dir,
        paths.meta_dir,
        paths.extraction_runs_dir,
        paths.research_dir,
        paths.analysis_dir,
        paths.bundles_dir,
        paths.provenance_dir,
    ]:
        directory.mkdir(parents=True, exist_ok=True)


def initialize_registry(
    paths: CompanyPaths,
    *,
    ticker: str,
    company_name: str,
    slug: str,
) -> dict[str, Any]:
    """Create or update the registry metadata file."""
    ensure_company_tree(paths)
    registry = load_registry(paths)
    now = utc_now()
    registry["root"] = str(paths.root)
    registry["ticker"] = ticker.upper()
    registry["company_name"] = company_name
    registry["slug"] = slug
    registry.setdefault("sources", [])
    registry["last_updated"] = now
    _write_registry(paths, registry)
    refresh_indexes(paths.root)
    return registry


def load_registry(paths: CompanyPaths) -> dict[str, Any]:
    """Load the source registry, returning an empty shell when missing."""
    if not paths.source_registry_json.exists():
        return {
            "root": str(paths.root),
            "ticker": None,
            "company_name": None,
            "slug": None,
            "sources": [],
            "last_updated": None,
        }
    import json

    return json.loads(paths.source_registry_json.read_text(encoding="utf-8"))


def list_sources(paths: CompanyPaths) -> list[dict[str, Any]]:
    """Return sources sorted by update time then identifier."""
    registry = load_registry(paths)
    return sorted(
        registry.get("sources", []),
        key=lambda item: (item.get("updated_at") or "", item["id"]),
    )


def upsert_source(
    paths: CompanyPaths,
    *,
    ticker: str,
    bucket: str,
    source_kind: str,
    status: str,
    title: str,
    local_path: str | None = None,
    url: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    """Insert or update a source in the registry."""
    if status not in SOURCE_STATUSES:
        raise ValueError(f"unsupported source status: {status}")
    ensure_company_tree(paths)
    registry = load_registry(paths)
    registry.setdefault("sources", [])
    entry_id = make_source_id(
        ticker=ticker,
        bucket=bucket,
        source_kind=source_kind,
        title=title,
        local_path=local_path,
        url=url,
    )
    now = utc_now()
    entry = next((item for item in registry["sources"] if item["id"] == entry_id), None)
    if entry is None:
        entry = {
            "id": entry_id,
            "title": title,
            "ticker": ticker.upper(),
            "bucket": bucket,
            "source_kind": source_kind,
            "status": status,
            "local_path": local_path,
            "url": url,
            "notes": notes,
            "created_at": now,
            "updated_at": now,
        }
        registry["sources"].append(entry)
    else:
        entry.update(
            {
                "title": title,
                "ticker": ticker.upper(),
                "bucket": bucket,
                "source_kind": source_kind,
                "status": status,
                "local_path": local_path,
                "url": url,
                "notes": notes,
                "updated_at": now,
            }
        )
    registry["ticker"] = registry.get("ticker") or ticker.upper()
    registry["last_updated"] = now
    _write_registry(paths, registry)
    refresh_indexes(paths.root)
    return entry


def normalize_local_path(paths: CompanyPaths, local_path: str | Path | None) -> str | None:
    """Normalize a source path relative to the company root when possible."""
    if local_path is None:
        return None
    candidate = Path(local_path).expanduser()
    if not candidate.is_absolute():
        candidate = (Path.cwd() / candidate).resolve()
    else:
        candidate = candidate.resolve()
    try:
        return str(candidate.relative_to(paths.root))
    except ValueError:
        return str(candidate)


def make_source_id(
    *,
    ticker: str,
    bucket: str,
    source_kind: str,
    title: str,
    local_path: str | None,
    url: str | None,
) -> str:
    """Create a deterministic registry identifier."""
    digest = hashlib.sha1(
        "|".join([ticker.upper(), bucket, source_kind, title, local_path or "", url or ""]).encode("utf-8")
    ).hexdigest()
    return digest[:12]


def utc_now() -> str:
    """Return an ISO-8601 UTC timestamp."""
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _write_registry(paths: CompanyPaths, registry: dict[str, Any]) -> None:
    write_json(paths.source_registry_json, registry)
    paths.source_registry_md.write_text(render_source_registry_markdown(registry) + "\n", encoding="utf-8")
