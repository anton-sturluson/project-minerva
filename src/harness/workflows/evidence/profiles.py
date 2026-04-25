"""Profile loading for evidence and analysis workflows."""

from __future__ import annotations

from typing import Any


def load_extract_profile(name: str) -> dict[str, Any]:
    """Load extraction profile. Reads from constants.py instead of YAML."""
    from harness.workflows.evidence.constants import EXTRACTION_QUESTIONS

    return {"name": name, "categories": {cat: {"questions": qs} for cat, qs in EXTRACTION_QUESTIONS.items()}}
