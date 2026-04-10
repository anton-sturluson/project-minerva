"""Profile loading for evidence and analysis workflows."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def load_extract_profile(name: str) -> dict[str, Any]:
    """Load an evidence extraction profile by name."""
    return _load_yaml(("evidence", "extract"), name)


def load_coverage_profile(name: str) -> dict[str, Any]:
    """Load an evidence coverage profile by name."""
    return _load_yaml(("evidence", "coverage"), name)


def load_context_profile(name: str) -> dict[str, Any]:
    """Load an analysis context profile by name."""
    return _load_yaml(("analysis", "context"), name)


def _load_yaml(segments: tuple[str, ...], name: str) -> dict[str, Any]:
    candidate = profiles_root().joinpath(*segments, f"{name}.yaml")
    if not candidate.exists() and name == "deep-dive":
        candidate = profiles_root().joinpath(*segments, "default.yaml")
    if not candidate.exists():
        joined = "/".join(segments)
        raise ValueError(f"profile `{name}` was not found under profiles/{joined}")
    payload = yaml.safe_load(candidate.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"profile `{name}` must deserialize to a mapping")
    payload.setdefault("name", name)
    return payload


def profiles_root() -> Path:
    """Return the repository-managed profile directory."""
    return Path(__file__).resolve().parents[4] / "profiles"
