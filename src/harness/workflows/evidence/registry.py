"""Registry state and company-tree helpers."""

from __future__ import annotations

from datetime import UTC, datetime
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
        paths.audits_dir,
        paths.plans_dir,
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


def utc_now() -> str:
    """Return an ISO-8601 UTC timestamp."""
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _write_registry(paths: CompanyPaths, registry: dict[str, Any]) -> None:
    write_json(paths.source_registry_json, registry)
    paths.source_registry_md.write_text(render_source_registry_markdown(registry) + "\n", encoding="utf-8")
