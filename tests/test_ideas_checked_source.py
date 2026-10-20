"""Validate archived original evidence through the shared source boundary."""

from datetime import date
from pathlib import Path
from uuid import UUID

import pytest

from harness.ideas import store
from harness.ideas.documents import SourceScope, archive, select_sections
from harness.ideas.extraction import Claim, View, materialize, passages
from harness.ideas.research import Match, checked_source


@pytest.mark.parametrize("revision", [None, 2, 3, 4])
def test_checked_source_preserves_legacy_and_scoped_original_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, revision: int | None
) -> None:
    """Actual archived content stays distinct from attribution for old and new identities."""
    monkeypatch.setenv("MINERVA_IDEAS_ROOT", str(tmp_path))
    run: dict = {"id": UUID(int=1), "issue_date": date(2026, 10, 14)}
    payload: bytes = b"<article><h1>Alpha Capital Q3 2026</h1><h2>Global Fund</h2><p>Acme has pricing power supporting durable margins and cash generation.</p></article>"

    def fetch(url: str) -> tuple[bytes, str]:
        """Provide original HTML bytes to the real archive parser."""
        return payload, url

    document: dict = select_sections(
        store.run_folder(run),
        archive(
            store.run_folder(run), "https://manager.example.com/report", fetch=fetch
        ),
        ["b2", "b3"],
        ["b1"],
    )
    original: dict = {
        "accepted": True,
        "reason": "Original source",
        "fund": "Global Fund",
        "company": "Acme",
        "period": "Q3 2026",
        "period_end": "2026-09-30",
        "publisher_block": "b1",
        "fund_block": "b2",
        "company_block": "b3",
        "period_block": "b1",
    }
    if revision is not None:
        original.update(
            policy_revision=revision,
            publisher="Alpha Capital",
            label_scope="specific",
            umbrella="",
            relationship_blocks=[],
        )
    snapshot: dict = (
        {**original, "relationship_blocks": []}
        if revision is not None
        else dict(original)
    )
    document["identity"] = original
    row: dict = {"company": "Acme", "fund": "Global Fund", "symbol": "ACME US"}
    scope: SourceScope
    identity: Match
    scope, identity = checked_source(row, run, document)
    assert [part["id"] for part in scope["content"]] == ["b2", "b3"]
    assert [part["id"] for part in scope["identity"]] == ["b1", "b2", "b3"]
    assert identity.publisher_quote == "Alpha Capital Q3 2026"
    assert (
        identity.company_quote
        == "Acme has pricing power supporting durable margins and cash generation."
    )
    assert identity.model_dump().get("policy_revision") == revision
    assert document["identity"] == snapshot
    proposal: View = View(
        instrument="equity",
        stance="bull",
        action="not stated",
        gap="",
        claims=[Claim(text="Acme has pricing power.", passages=["b3.1"])],
    )
    assert (
        materialize(proposal, passages(scope["content"]))["claims"][0]["evidence"][0][
            "quote"
        ]
        == identity.company_quote
    )
    proposal.claims[0].passages = ["b1.1"]
    with pytest.raises(ValueError, match="unknown source passage"):
        materialize(proposal, passages(scope["content"]))
    with pytest.raises(ValueError, match="selected content"):
        checked_source(
            row, run, {**document, "identity": {**original, "fund_block": "b1"}}
        )
    with pytest.raises(ValueError, match="company does not match"):
        checked_source(
            {**row, "company": "Different Issuer", "symbol": "DIFF US"}, run, document
        )
    with pytest.raises(ValueError, match="not later than"):
        checked_source(
            row, run, {**document, "identity": {**original, "period_end": "2026-11-30"}}
        )
