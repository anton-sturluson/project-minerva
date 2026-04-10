"""Rendering helpers for workflow metadata and directory indexes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from minerva.formatting import build_markdown_table


def write_json(path: Path, payload: dict[str, Any]) -> None:
    """Persist indented JSON with a trailing newline."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def render_source_registry_markdown(registry: dict[str, Any]) -> str:
    """Render the registry to a compact markdown summary."""
    rows: list[list[str]] = []
    for entry in registry.get("sources", []):
        rows.append(
            [
                entry["id"],
                entry["status"],
                entry["bucket"],
                entry["source_kind"],
                entry["title"],
                entry.get("local_path") or "",
                entry.get("url") or "",
            ]
        )
    table = build_markdown_table(
        ["id", "status", "bucket", "source_kind", "title", "local_path", "url"],
        rows or [["(none)", "", "", "", "", "", ""]],
        alignment=["l", "l", "l", "l", "l", "l", "l"],
    )
    return "\n".join(
        [
            "# Source Registry",
            "",
            f"- ticker: {registry.get('ticker') or '(unknown)'}",
            f"- company_name: {registry.get('company_name') or '(unknown)'}",
            f"- slug: {registry.get('slug') or '(unknown)'}",
            f"- source_count: {len(registry.get('sources', []))}",
            f"- last_updated: {registry.get('last_updated') or '(unknown)'}",
            "",
            "## Sources",
            "",
            table,
        ]
    )


def render_inventory_markdown(inventory: dict[str, Any]) -> str:
    """Render inventory counts and disk-health summary."""
    counts = inventory.get("counts", {})
    rows = [[key, str(value)] for key, value in sorted(counts.items())]
    missing_rows = [[path] for path in inventory.get("downloaded_missing_on_disk", [])]
    return "\n".join(
        [
            "# Evidence Inventory",
            "",
            f"- root: {inventory.get('root')}",
            f"- last_updated: {inventory.get('last_updated')}",
            "",
            "## Counts",
            "",
            build_markdown_table(["metric", "value"], rows or [["(none)", "0"]], alignment=["l", "r"]),
            "",
            "## Downloaded Missing On Disk",
            "",
            build_markdown_table(["path"], missing_rows or [["(none)"]], alignment=["l"]),
        ]
    )


def render_coverage_markdown(coverage: dict[str, Any]) -> str:
    """Render coverage status by bucket."""
    rows: list[list[str]] = []
    for result in coverage.get("bucket_results", []):
        rows.append(
            [
                result["bucket"],
                result["status"],
                str(result["target_count"]),
                str(result["downloaded_count"]),
                str(result["discovered_count"]),
                str(result["blocked_count"]),
                result.get("notes") or "",
            ]
        )
    return "\n".join(
        [
            "# Evidence Coverage",
            "",
            f"- profile: {coverage.get('profile')}",
            f"- ready_for_analysis: {coverage.get('ready_for_analysis')}",
            f"- last_updated: {coverage.get('last_updated')}",
            "",
            build_markdown_table(
                ["bucket", "status", "target", "downloaded", "discovered", "blocked", "notes"],
                rows or [["(none)", "missing", "0", "0", "0", "0", ""]],
                alignment=["l", "l", "r", "r", "r", "r", "l"],
            ),
        ]
    )


def render_extraction_run_markdown(run: dict[str, Any]) -> str:
    """Render an extraction run manifest."""
    rows = [
        [
            item["source_id"],
            item["status"],
            item.get("structured_json") or "",
            item.get("structured_markdown") or "",
        ]
        for item in run.get("artifacts", [])
    ]
    return "\n".join(
        [
            "# Extraction Run",
            "",
            f"- profile: {run.get('profile')}",
            f"- model: {run.get('model')}",
            f"- processed: {run.get('processed_count', 0)}",
            f"- skipped_existing: {run.get('skipped_existing_count', 0)}",
            f"- total_matches: {run.get('matched_count', 0)}",
            f"- created_at: {run.get('created_at')}",
            "",
            build_markdown_table(
                ["source_id", "status", "structured_json", "structured_markdown"],
                rows or [["(none)", "skipped", "", ""]],
                alignment=["l", "l", "l", "l"],
            ),
        ]
    )


def render_analysis_status_markdown(status_payload: dict[str, Any]) -> str:
    """Render analysis workflow status."""
    rows = [[item["name"], item["status"], item.get("detail") or ""] for item in status_payload.get("milestones", [])]
    return "\n".join(
        [
            "# Analysis Status",
            "",
            f"- stage: {status_payload.get('stage')}",
            f"- next_step: {status_payload.get('next_step')}",
            f"- last_updated: {status_payload.get('last_updated')}",
            "",
            build_markdown_table(
                ["milestone", "status", "detail"],
                rows or [["(none)", "pending", ""]],
                alignment=["l", "l", "l"],
            ),
        ]
    )


def render_context_manifest_markdown(manifest: dict[str, Any]) -> str:
    """Render analysis context manifest summary."""
    rows = [
        [
            bundle["name"],
            bundle["path"],
            str(bundle["artifact_count"]),
            str(bundle["estimated_tokens"]),
        ]
        for bundle in manifest.get("bundles", [])
    ]
    return "\n".join(
        [
            "# Analysis Context Manifest",
            "",
            f"- profile: {manifest.get('profile')}",
            f"- estimated_tokens: {manifest.get('estimated_tokens')}",
            f"- last_updated: {manifest.get('last_updated')}",
            "",
            build_markdown_table(
                ["bundle", "path", "artifact_count", "estimated_tokens"],
                rows or [["(none)", "", "0", "0"]],
                alignment=["l", "l", "r", "r"],
            ),
        ]
    )


def refresh_indexes(root: Path) -> None:
    """Write a simple directory listing index for every non-hidden directory under root."""
    for directory in sorted(_iter_directories(root)):
        index_path = directory / "INDEX.md"
        lines: list[str] = [f"# Index: {directory.name}", ""]
        children = sorted(directory.iterdir(), key=lambda item: (item.is_file(), item.name.lower()))
        directories = [item for item in children if item.is_dir() and not item.name.startswith(".")]
        files = [item for item in children if item.is_file() and item.name != "INDEX.md" and not item.name.startswith(".")]
        lines.append("## Directories")
        lines.append("")
        if directories:
            lines.extend([f"- {item.name}/" for item in directories])
        else:
            lines.append("- (none)")
        lines.extend(["", "## Files", ""])
        if files:
            lines.extend([f"- {item.name}" for item in files])
        else:
            lines.append("- (none)")
        index_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _iter_directories(root: Path) -> list[Path]:
    directories: list[Path] = []
    if not root.exists():
        return directories
    for directory in root.rglob("*"):
        if directory.is_dir() and not any(part.startswith(".") for part in directory.relative_to(root).parts):
            directories.append(directory)
    directories.append(root)
    return directories
