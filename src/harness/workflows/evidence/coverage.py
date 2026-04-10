"""Coverage evaluation against explicit profile targets."""

from __future__ import annotations

from typing import Any

from harness.workflows.evidence.paths import CompanyPaths
from harness.workflows.evidence.profiles import load_coverage_profile
from harness.workflows.evidence.registry import list_sources, utc_now
from harness.workflows.evidence.render import render_coverage_markdown, write_json


def run_coverage(paths: CompanyPaths, *, profile_name: str) -> dict[str, Any]:
    """Compare registry state against a named coverage profile."""
    profile = load_coverage_profile(profile_name)
    targets = profile.get("targets", [])
    if not isinstance(targets, list) or not targets:
        raise ValueError(f"coverage profile `{profile_name}` has no targets")

    sources = list_sources(paths)
    bucket_results: list[dict[str, Any]] = []
    for target in targets:
        bucket = str(target["bucket"])
        target_count = int(target.get("target_count", 1))
        matches = [entry for entry in sources if entry["bucket"] == bucket]
        downloaded_count = len([entry for entry in matches if entry["status"] == "downloaded"])
        discovered_count = len([entry for entry in matches if entry["status"] == "discovered"])
        blocked_count = len([entry for entry in matches if entry["status"] == "blocked"])
        status = _bucket_status(
            target_count=target_count,
            downloaded_count=downloaded_count,
            discovered_count=discovered_count,
            blocked_count=blocked_count,
        )
        bucket_results.append(
            {
                "bucket": bucket,
                "label": target.get("label") or bucket,
                "target_count": target_count,
                "downloaded_count": downloaded_count,
                "discovered_count": discovered_count,
                "blocked_count": blocked_count,
                "status": status,
                "notes": target.get("notes") or "",
            }
        )

    payload = {
        "profile": profile_name,
        "bucket_results": bucket_results,
        "ready_for_analysis": all(item["status"] == "good" for item in bucket_results),
        "last_updated": utc_now(),
    }
    write_json(paths.coverage_json, payload)
    paths.coverage_md.write_text(render_coverage_markdown(payload) + "\n", encoding="utf-8")
    return payload


def _bucket_status(*, target_count: int, downloaded_count: int, discovered_count: int, blocked_count: int) -> str:
    if downloaded_count >= target_count:
        return "good"
    if blocked_count > 0 and downloaded_count + discovered_count < target_count:
        return "blocked"
    if downloaded_count > 0 or discovered_count > 0:
        return "partial"
    return "missing"
