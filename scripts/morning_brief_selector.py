#!/usr/bin/env python3
"""Build Terra's morning-brief relevance prompt with same-run portfolio context."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PORTFOLIO_ROLES = frozenset({"holding", "watchlist"})
IDENTITY_FIELDS = ("security_id", "ticker", "company_name")


def universe_membership(item: dict[str, Any]) -> str:
    """Return holding/watchlist membership, preferring canonical source metadata."""
    sources = item.get("sources")
    if isinstance(sources, list):
        source_roles = {
            str(source).strip().casefold()
            for source in sources
            if str(source).strip()
        }
        for role in ("holding", "watchlist"):
            if role in source_roles:
                return role

    # ``relationship`` is retained as a compatibility fallback for older
    # prepared-evidence universes.
    for field in ("source_kind", "relationship"):
        role = str(item.get(field) or "").strip().casefold()
        if role in PORTFOLIO_ROLES:
            return role
    return ""


def compact_portfolio_context(
    universe: list[Any],
) -> dict[str, list[dict[str, Any]]]:
    """Return a deterministic identity-only holding/watchlist context."""
    context: dict[str, list[dict[str, Any]]] = {
        "holdings": [],
        "watchlist": [],
    }
    for item in universe:
        if not isinstance(item, dict):
            continue
        membership = universe_membership(item)
        if not membership:
            continue
        identity = {field: item[field] for field in IDENTITY_FIELDS if field in item}
        context["holdings" if membership == "holding" else "watchlist"].append(
            identity
        )

    for records in context.values():
        records.sort(
            key=lambda record: (
                str(record.get("security_id") or "").casefold(),
                str(record.get("ticker") or "").casefold(),
                str(record.get("company_name") or "").casefold(),
                json.dumps(
                    record,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            )
        )
    return context


def portfolio_context_from_prepared_evidence(
    prepared_evidence: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    """Extract compact context from the universe embedded in prepared evidence."""
    universe = prepared_evidence.get("universe", [])
    if not isinstance(universe, list):
        raise ValueError("prepared evidence `universe` must be a list")
    return compact_portfolio_context(universe)


def load_portfolio_context(
    prepared_evidence_path: Path,
) -> dict[str, list[dict[str, Any]]]:
    """Load prepared evidence and return its compact portfolio context."""
    prepared_evidence = json.loads(
        prepared_evidence_path.read_text(encoding="utf-8")
    )
    if not isinstance(prepared_evidence, dict):
        raise ValueError("prepared evidence must be a JSON object")
    return portfolio_context_from_prepared_evidence(prepared_evidence)


def render_relevance_prompt(
    selection_prompt: str,
    portfolio_context: dict[str, list[dict[str, Any]]],
) -> str:
    """Append identity-only context and relevance policy to Terra's base prompt."""
    context_json = json.dumps(
        portfolio_context,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return (
        selection_prompt.rstrip()
        + "\n\n## Same-run portfolio/watchlist context\n\n"
        "The compact JSON below comes from the universe embedded in this run's "
        "prepared evidence. It contains only security identity fields. Treat holding "
        "or watchlist membership as an important positive relevance signal, but not "
        "as automatic selection. Include articles with material direct relevance or "
        "material read-through relevance to these securities when they meet the "
        "selection criteria.\n\n"
        f"PORTFOLIO_CONTEXT_JSON:\n{context_json}\n"
    )


def build_relevance_prompt(
    *, selection_prompt_path: Path, prepared_evidence_path: Path
) -> str:
    """Build the complete contextual Terra relevance prompt from run artifacts."""
    selection_prompt = selection_prompt_path.read_text(encoding="utf-8")
    context = load_portfolio_context(prepared_evidence_path)
    return render_relevance_prompt(selection_prompt, context)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection-prompt", type=Path, required=True)
    parser.add_argument("--prepared-evidence", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        rendered = build_relevance_prompt(
            selection_prompt_path=args.selection_prompt,
            prepared_evidence_path=args.prepared_evidence,
        )
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered, encoding="utf-8")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
