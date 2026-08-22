"""Focused tests for Terra's contextual morning-brief relevance prompt."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SELECTOR_PATH = REPO_ROOT / "scripts" / "morning_brief_selector.py"
SPEC = importlib.util.spec_from_file_location("morning_brief_selector", SELECTOR_PATH)
assert SPEC is not None and SPEC.loader is not None
selector = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(selector)


def test_context_uses_membership_precedence_and_identity_whitelist() -> None:
    prepared = {
        "universe": [
            {
                "security_id": "WATCH",
                "ticker": "WCH",
                "company_name": "Watch Co",
                "sources": ["watchlist"],
                "source_kind": "holding",
                "notes": "source membership wins",
            },
            {
                "security_id": "HOLD",
                "ticker": "HLD",
                "company_name": "Holding Co",
                "sources": ["watchlist", "holding"],
                "source_kind": "watchlist",
                "shares": 125,
                "weight": 0.15,
            },
            {
                "security_id": "ALPHA",
                "ticker": "ALP",
                "company_name": "Alpha Co",
                "source_kind": "holding",
            },
            {
                "security_id": "LEGACY",
                "ticker": "LEG",
                "relationship": "watchlist",
            },
            {
                "security_id": "ADJACENT",
                "ticker": "ADJ",
                "source_kind": "adjacent",
            },
            "malformed row",
        ]
    }

    context = selector.portfolio_context_from_prepared_evidence(prepared)

    assert context == {
        "holdings": [
            {
                "security_id": "ALPHA",
                "ticker": "ALP",
                "company_name": "Alpha Co",
            },
            {
                "security_id": "HOLD",
                "ticker": "HLD",
                "company_name": "Holding Co",
            },
        ],
        "watchlist": [
            {"security_id": "LEGACY", "ticker": "LEG"},
            {
                "security_id": "WATCH",
                "ticker": "WCH",
                "company_name": "Watch Co",
            },
        ],
    }
    assert all(
        set(record) <= {"security_id", "ticker", "company_name"}
        for records in context.values()
        for record in records
    )


def test_missing_universe_is_empty_but_non_list_universe_is_rejected() -> None:
    assert selector.portfolio_context_from_prepared_evidence({}) == {
        "holdings": [],
        "watchlist": [],
    }

    with pytest.raises(
        ValueError, match=r"prepared evidence `universe` must be a list"
    ):
        selector.portfolio_context_from_prepared_evidence(
            {"universe": {"security_id": "HOLD"}}
        )


@pytest.mark.parametrize("universe", [[], None])
def test_selector_cli_writes_contextual_prompt_or_rejects_bad_universe(
    tmp_path: Path, universe: list[object] | None
) -> None:
    base_prompt = tmp_path / "selection.md"
    base_prompt.write_text("Select relevant articles.\n", encoding="utf-8")
    prepared = tmp_path / "prepared-evidence.json"
    payload = {} if universe == [] else {"universe": universe}
    prepared.write_text(json.dumps(payload), encoding="utf-8")
    output = tmp_path / "relevance-prompt.md"

    status = selector.main(
        [
            "--selection-prompt",
            str(base_prompt),
            "--prepared-evidence",
            str(prepared),
            "--out",
            str(output),
        ]
    )

    if universe == []:
        assert status == 0
        rendered = output.read_text(encoding="utf-8")
        assert rendered.startswith("Select relevant articles.\n")
        assert (
            'PORTFOLIO_CONTEXT_JSON:\n{"holdings":[],"watchlist":[]}'
            in rendered
        )
        assert (
            "important positive relevance signal, but not as automatic selection"
            in rendered
        )
        assert (
            "material direct relevance or material read-through relevance" in rendered
        )
    else:
        assert status == 1
        assert not output.exists()


def test_rendered_prompt_excludes_unrelated_universe_fields(tmp_path: Path) -> None:
    selection_prompt = tmp_path / "selection.md"
    selection_prompt.write_text("Base Terra policy.\n", encoding="utf-8")
    prepared = tmp_path / "prepared-evidence.json"
    prepared.write_text(
        json.dumps(
            {
                "universe": [
                    {
                        "security_id": "PORT",
                        "ticker": "PRT",
                        "company_name": "Portfolio Inc",
                        "sources": ["holding"],
                        "shares": 999,
                        "weight": 0.42,
                        "notes": "private monitoring note",
                        "unrelated": {"secret": True},
                    }
                ],
                "events": [{"headline": "unrelated prepared event"}],
            }
        ),
        encoding="utf-8",
    )

    rendered = selector.build_relevance_prompt(
        selection_prompt_path=selection_prompt,
        prepared_evidence_path=prepared,
    )

    assert (
        '"holdings":[{"company_name":"Portfolio Inc","security_id":"PORT",'
        '"ticker":"PRT"}]' in rendered
    )
    for excluded in (
        "shares",
        "weight",
        "private monitoring note",
        "unrelated",
        "secret",
        "unrelated prepared event",
    ):
        assert excluded not in rendered


def test_synthesis_keeps_existing_article_boundary_and_uses_contextual_prompt() -> None:
    contract = (
        REPO_ROOT / "scripts" / "prompts" / "morning_brief_synthesis.md"
    ).read_text(encoding="utf-8")

    assert "morning_brief_selector.py" in contract
    assert '--prepared-evidence "$PREPARED_EVIDENCE"' in contract
    assert '--questions-file "$SELECTION_TMP/relevance-prompt.md"' in contract
    assert (
        "Each line must contain exactly `article_key`, `url`, `title`, `source`, "
        "`published_at`, and `summary`; do not add article bodies or other fields."
        in contract
    )
    assert "--model gpt-5.6-terra" in contract
    assert "--thinking high" in contract
