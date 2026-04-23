"""Inventory computation over the evidence tree."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from harness.workflows.evidence.ledger import load_ledger, utc_now
from harness.workflows.evidence.paths import CompanyPaths
from harness.workflows.evidence.registry import ensure_company_tree
from harness.workflows.evidence.render import refresh_indexes, render_inventory_markdown, write_json


def build_inventory(paths: CompanyPaths) -> dict[str, Any]:
    """Compute deterministic inventory counts from the V2 ledger and filesystem."""
    ensure_company_tree(paths)
    entries = load_ledger(paths)
    downloaded_missing_on_disk: list[str] = []
    downloaded_count = 0
    discovered_count = 0
    blocked_count = 0

    for entry in entries:
        if entry["status"] == "downloaded":
            downloaded_count += 1
            if not _source_exists(paths, entry.get("local_path")):
                downloaded_missing_on_disk.append(entry.get("local_path") or "(missing path)")
        elif entry["status"] == "discovered":
            discovered_count += 1
        elif entry["status"] == "blocked":
            blocked_count += 1

    extracted_files = len(
        [
            item
            for item in paths.structured_dir.rglob("*")
            if _is_tracked_artifact_file(item) and item.suffix in {".json", ".md"}
        ]
    )
    source_files = len([item for item in paths.sources_dir.rglob("*") if _is_tracked_artifact_file(item)])
    reference_files = len([item for item in paths.references_dir.rglob("*") if _is_tracked_artifact_file(item)])

    return {
        "root": str(paths.root),
        "counts": {
            "ledger_total": len(entries),
            "downloaded": downloaded_count,
            "discovered": discovered_count,
            "blocked": blocked_count,
            "downloaded_missing_on_disk": len(downloaded_missing_on_disk),
            "source_files": source_files,
            "reference_files": reference_files,
            "extracted_files": extracted_files,
        },
        "downloaded_missing_on_disk": sorted(downloaded_missing_on_disk),
        "last_updated": utc_now(),
    }


def write_inventory(paths: CompanyPaths, inventory: dict[str, Any], *, write_index: bool = True) -> None:
    """Persist inventory artifacts."""
    write_json(paths.inventory_json, inventory)
    paths.inventory_md.write_text(render_inventory_markdown(inventory) + "\n", encoding="utf-8")
    if write_index:
        refresh_indexes(paths.root)


def run_inventory(paths: CompanyPaths, *, write_index: bool = True) -> dict[str, Any]:
    """Build and persist inventory state."""
    inventory = build_inventory(paths)
    write_inventory(paths, inventory, write_index=write_index)
    return inventory


def _source_exists(paths: CompanyPaths, local_path: str | None) -> bool:
    if not local_path:
        return False
    candidate = Path(local_path)
    if candidate.is_absolute():
        return candidate.exists()
    return (paths.root / candidate).exists()


def _is_tracked_artifact_file(path: Path) -> bool:
    return path.is_file() and not path.name.startswith(".") and path.name != "INDEX.md"
