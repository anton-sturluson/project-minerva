"""Deterministic workflow status for deep-dive analysis."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from harness.workflows.evidence.paths import CompanyPaths
from harness.workflows.evidence.registry import load_registry, utc_now
from harness.workflows.evidence.render import render_analysis_status_markdown, write_json

FOLDER_INDEX_STEMS: frozenset[str] = frozenset({"index", "readme"})


def run_status(paths: CompanyPaths) -> dict[str, Any]:
    """Compute and persist the current analysis workflow status."""
    registry = load_registry(paths)
    inventory = _load_json(paths.inventory_json)
    coverage = _load_json(paths.coverage_json)
    context_manifest = _load_json(paths.context_manifest_json)

    notes = _list_stage_artifacts(paths.notes_dir, suffixes={".md"})
    provenance = _list_stage_artifacts(paths.provenance_dir)
    bundles = _list_stage_artifacts(paths.bundles_dir, suffixes={".md"})
    extracted_count = inventory.get("counts", {}).get("extracted_files", 0) if inventory else 0
    coverage_ready = bool(coverage.get("ready_for_analysis")) if coverage else False
    source_count = len(registry.get("sources", []))

    if provenance:
        stage = "complete"
    elif notes:
        stage = "memo-in-progress"
    elif bundles or context_manifest:
        stage = "analysis-in-progress"
    elif coverage_ready and extracted_count > 0:
        stage = "analysis-ready"
    elif coverage_ready:
        stage = "extracting"
    elif source_count > 0:
        stage = "collecting"
    else:
        stage = "initialized"

    payload = {
        "stage": stage,
        "next_step": _next_step(paths, registry=registry, inventory=inventory, coverage=coverage, extracted_count=extracted_count, bundles=bundles),
        "milestones": [
            {"name": "registry", "status": "done" if paths.source_registry_json.exists() else "missing", "detail": str(paths.source_registry_json.relative_to(paths.root))},
            {"name": "inventory", "status": "done" if paths.inventory_json.exists() else "missing", "detail": str(paths.inventory_json.relative_to(paths.root))},
            {"name": "coverage", "status": "done" if paths.coverage_json.exists() else "missing", "detail": str(paths.coverage_json.relative_to(paths.root))},
            {"name": "structured-extraction", "status": "done" if extracted_count > 0 else "missing", "detail": f"extracted_files={extracted_count}"},
            {"name": "analysis-context", "status": "done" if bundles else "missing", "detail": f"bundle_count={len(bundles)}"},
            {"name": "notes", "status": "done" if notes else "missing", "detail": f"note_count={len(notes)}"},
            {"name": "provenance", "status": "done" if provenance else "missing", "detail": f"record_count={len(provenance)}"},
        ],
        "last_updated": utc_now(),
    }
    write_json(paths.status_json, payload)
    paths.status_md.write_text(render_analysis_status_markdown(payload) + "\n", encoding="utf-8")
    return payload


def _next_step(
    paths: CompanyPaths,
    *,
    registry: dict[str, Any],
    inventory: dict[str, Any] | None,
    coverage: dict[str, Any] | None,
    extracted_count: int,
    bundles: list[Path],
) -> str:
    ticker = registry.get("ticker") or paths.root.name.upper()
    if not registry.get("sources"):
        return f"minerva evidence collect sec --root {paths.root} --ticker {ticker}"
    if not inventory:
        return f"minerva evidence inventory --root {paths.root}"
    if not coverage:
        return f"minerva evidence coverage --root {paths.root} --profile default"
    if not coverage.get("ready_for_analysis"):
        missing = next((item["bucket"] for item in coverage.get("bucket_results", []) if item["status"] != "good"), "missing-bucket")
        if missing.startswith("sec-"):
            return f"minerva evidence collect sec --root {paths.root} --ticker {ticker}"
        return f"minerva evidence register --root {paths.root} --status discovered --bucket {missing} --source-kind external-research --title \"Add source\""
    if extracted_count == 0:
        return f"minerva evidence extract --root {paths.root} --profile default"
    if not bundles:
        return f"minerva analysis context --root {paths.root} --profile default"
    return f"minerva extract \"What matters most and why?\" --file {paths.bundles_dir / 'business-overview.md'}"


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _list_stage_artifacts(directory: Path, *, suffixes: set[str] | None = None) -> list[Path]:
    """List stage-driving files, excluding generated folder indexes and hidden files."""
    if not directory.exists():
        return []

    artifacts: list[Path] = []
    for item in sorted(directory.iterdir(), key=lambda candidate: candidate.name.lower()):
        if not item.is_file() or item.name.startswith(".") or _is_folder_index_artifact(item):
            continue
        if suffixes is not None and item.suffix.lower() not in suffixes:
            continue
        artifacts.append(item)
    return artifacts


def _is_folder_index_artifact(path: Path) -> bool:
    """Return True for common generated folder index files like INDEX.md."""
    return path.stem.lower() in FOLDER_INDEX_STEMS
