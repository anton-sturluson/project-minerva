"""Build bounded analysis context bundles from extracted artifacts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from harness.workflows.evidence.extraction import structured_output_base
from harness.workflows.evidence.paths import CompanyPaths
from harness.workflows.evidence.profiles import load_context_profile
from harness.workflows.evidence.registry import list_sources, utc_now
from harness.workflows.evidence.render import refresh_indexes, render_context_manifest_markdown, write_json


def run_context(paths: CompanyPaths, *, profile_name: str) -> dict[str, Any]:
    """Build section bundles from extracted structured outputs."""
    profile = load_context_profile(profile_name)
    bundles_config = profile.get("bundles", [])
    if not isinstance(bundles_config, list) or not bundles_config:
        raise ValueError(f"context profile `{profile_name}` has no bundles")

    all_sources = list_sources(paths)
    manifest_bundles: list[dict[str, Any]] = []
    included_artifacts: list[dict[str, Any]] = []
    total_tokens = 0

    for bundle in bundles_config:
        name = str(bundle["name"])
        bundle_path = paths.bundles_dir / f"{name}.md"
        selected_sources = _select_sources(all_sources, bundle)
        artifact_sections: list[str] = [f"# {name.replace('-', ' ').title()}", ""]
        artifact_count = 0
        bundle_tokens = 0

        for entry in selected_sources:
            markdown_path = structured_output_base(paths, entry).with_suffix(".md")
            if not markdown_path.exists():
                continue
            body = markdown_path.read_text(encoding="utf-8").strip()
            artifact_sections.extend(
                [
                    f"## Artifact: {entry['title']}",
                    "",
                    f"- source_id: {entry['id']}",
                    f"- bucket: {entry['bucket']}",
                    f"- source_kind: {entry['source_kind']}",
                    f"- structured_path: {markdown_path.relative_to(paths.root)}",
                    "",
                    body,
                    "",
                ]
            )
            artifact_count += 1
            bundle_tokens += estimate_tokens(body)
            included_artifacts.append(
                {
                    "bundle": name,
                    "source_id": entry["id"],
                    "source_title": entry["title"],
                    "structured_markdown": str(markdown_path.relative_to(paths.root)),
                }
            )

        for pattern in bundle.get("extra_globs", []):
            for extra_path in sorted(paths.root.glob(pattern)):
                if not extra_path.is_file():
                    continue
                text = extra_path.read_text(encoding="utf-8").strip()
                artifact_sections.extend([f"## Artifact: {extra_path.name}", "", text, ""])
                artifact_count += 1
                bundle_tokens += estimate_tokens(text)
                included_artifacts.append(
                    {
                        "bundle": name,
                        "source_id": extra_path.name,
                        "source_title": extra_path.name,
                        "structured_markdown": str(extra_path.relative_to(paths.root)),
                    }
                )

        if artifact_count == 0:
            artifact_sections.extend(["No extracted artifacts matched this bundle yet.", ""])
        bundle_path.parent.mkdir(parents=True, exist_ok=True)
        bundle_path.write_text("\n".join(artifact_sections).rstrip() + "\n", encoding="utf-8")
        manifest_bundles.append(
            {
                "name": name,
                "path": str(bundle_path.relative_to(paths.root)),
                "artifact_count": artifact_count,
                "estimated_tokens": bundle_tokens,
            }
        )
        total_tokens += bundle_tokens

    manifest = {
        "profile": profile_name,
        "included_artifacts": included_artifacts,
        "bundle_paths": [item["path"] for item in manifest_bundles],
        "bundles": manifest_bundles,
        "estimated_tokens": total_tokens,
        "last_updated": utc_now(),
    }
    write_json(paths.context_manifest_json, manifest)
    paths.context_manifest_md.write_text(render_context_manifest_markdown(manifest) + "\n", encoding="utf-8")
    refresh_indexes(paths.root)
    return manifest


def estimate_tokens(text: str) -> int:
    """Use a simple char-based approximation for bundle sizing."""
    return max(1, len(text) // 4)


def _select_sources(all_sources: list[dict[str, Any]], bundle: dict[str, Any]) -> list[dict[str, Any]]:
    buckets = set(bundle.get("buckets", []))
    source_kinds = set(bundle.get("source_kinds", []))
    selected = []
    for entry in all_sources:
        if entry["status"] != "downloaded":
            continue
        if buckets and entry["bucket"] not in buckets:
            continue
        if source_kinds and entry["source_kind"] not in source_kinds:
            continue
        selected.append(entry)
    return sorted(selected, key=lambda item: (item["bucket"], item["source_kind"], item["title"]))
