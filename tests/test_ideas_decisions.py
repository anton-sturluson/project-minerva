"""Check reusable evidence decisions and explicit source relationships."""

from datetime import date
from pathlib import Path
from uuid import UUID

import pytest

from harness.ideas import decisions, store
from harness.ideas.extraction import Claim, View, review_proposal
from harness.ideas.research import (
    EvidenceIdentity,
    LabelScope,
    Match,
    resolve_identity,
    validate_match,
)


def identity(
    fund: str,
    publisher: str,
    scope: LabelScope,
    *,
    umbrella: str = "",
    relationship_blocks: list[str] | None = None,
) -> EvidenceIdentity:
    """Build synthetic observed identities without private manager records."""
    return EvidenceIdentity(
        accepted=True,
        reason="Original evidence",
        fund=fund,
        company="Acme",
        publisher=publisher,
        label_scope=scope,
        umbrella=umbrella,
        period="Q2 2026",
        period_end=date(2026, 6, 30),
        publisher_block="p1",
        fund_block="p2",
        company_block="p3",
        period_block="p1",
        relationship_blocks=relationship_blocks or [],
    )


def validate(
    candidate: EvidenceIdentity, label: str, parts: list[dict[str, str]]
) -> Match:
    """Run normal source gates against exact archived synthetic source blocks."""
    resolved: Match = resolve_identity(candidate.model_dump(), parts)
    validate_match(
        resolved,
        parts,
        date(2026, 10, 14),
        {"company": "Acme", "fund": label, "symbol": "ACME US"},
    )
    return resolved


def test_manager_label_requires_original_publisher_and_member_relationship() -> None:
    """A broad manager lead may identify its own named fund without losing constraints."""
    parts: list[dict[str, str]] = [
        {"id": "p1", "text": "Harbor Capital Q2 2026"},
        {"id": "p2", "text": "Harbor Capital manages Harbor Global Growth Fund."},
        {"id": "p3", "text": "Acme has durable pricing power."},
    ]
    candidate: EvidenceIdentity = identity(
        "Harbor Global Growth Fund",
        "Harbor Capital",
        "manager",
        relationship_blocks=["p2"],
    )
    validate(candidate, "Harbor Capital", parts)
    with pytest.raises(ValueError, match="discard a specific fund constraint"):
        validate(candidate, "Harbor Capital Sustainable", parts)
    candidate.relationship_blocks = []
    with pytest.raises(ValueError, match="relationship evidence"):
        validate(candidate, "Harbor Capital", parts)


def test_combined_label_requires_a_named_member_and_joint_original_evidence() -> None:
    """A two-fund report can support one member without asserting the other owns it."""
    parts: list[dict[str, str]] = [
        {
            "id": "p1",
            "text": "Harbor Capital Q2 2026: Australian Shares Fund and International Shares Fund joint report.",
        },
        {"id": "p2", "text": "Harbor International Shares Fund"},
        {"id": "p3", "text": "Acme has durable pricing power."},
    ]
    label: str = "Harbor Funds (Australian Shares Fund and International Shares Fund)"
    candidate: EvidenceIdentity = identity(
        "Harbor International Shares Fund",
        "Harbor Capital",
        "combined",
        relationship_blocks=["p1", "p2"],
    )
    validate(candidate, label, parts)
    candidate.fund = "Harbor Global Shares Fund"
    parts[1]["text"] = candidate.fund
    with pytest.raises(ValueError, match="not an explicitly named"):
        validate(candidate, label, parts)


def test_umbrella_title_and_contents_can_prove_the_original_member() -> None:
    """A legal title prefix is evidenced in the umbrella, not globally removed."""
    parts: list[dict[str, str]] = [
        {"id": "p1", "text": "WS Harbor Investment Funds — Harbor Capital — Q2 2026"},
        {
            "id": "p2",
            "text": "Contents: Harbor Global Innovation Fund; Harbor Small Cap Fund.",
        },
        {"id": "p3", "text": "Acme has durable pricing power."},
    ]
    candidate: EvidenceIdentity = identity(
        "Harbor Global Innovation Fund",
        "Harbor Capital",
        "umbrella",
        umbrella="WS Harbor Investment Funds",
        relationship_blocks=["p1", "p2"],
    )
    validate(candidate, "Harbor Investment Funds", parts)
    candidate.relationship_blocks = ["p2"]
    with pytest.raises(ValueError, match="explicitly link"):
        validate(candidate, "Harbor Investment Funds", parts)


@pytest.mark.parametrize(
    "label",
    [
        "Harbour Global Fund",
        "Harbor US Global Fund",
        "Harbor Sustainable Global Fund",
        "Harbor Global UCITS Fund",
    ],
)
def test_specific_label_never_discards_spelling_region_style_or_vehicle(
    label: str,
) -> None:
    """Publisher evidence does not authorize sibling funds or fuzzy spelling changes."""
    parts: list[dict[str, str]] = [
        {"id": "p1", "text": "Harbor Capital Q2 2026"},
        {"id": "p2", "text": "Harbor Global Fund"},
        {"id": "p3", "text": "Acme has durable pricing power."},
    ]
    with pytest.raises(ValueError, match="fund does not match"):
        validate(
            identity("Harbor Global Fund", "Harbor Capital", "specific"), label, parts
        )


def test_decisions_ignore_url_model_and_delegation_but_bind_scope_and_policy(
    tmp_path: Path,
) -> None:
    """Identical bytes cannot reopen a rejection through URL or model changes."""
    row: dict = {"company": "Acme", "fund": "Harbor Fund", "symbol": "ACME US"}
    run: dict = {"issue_date": date(2026, 10, 14)}
    document: dict = {"sha256": "a" * 64, "url": "https://example.com/original.pdf"}
    evidence: decisions.EvidenceBasis = decisions.basis(row, run, document, "identity")
    decision: decisions.EvidenceDecision = decisions.EvidenceDecision(
        basis=evidence,
        outcome="rejected",
        reason="Wrong fund",
        document=document,
        result={},
    )
    decisions.save(tmp_path, decision)
    alias: decisions.EvidenceBasis = decisions.basis(
        row,
        run,
        {
            **document,
            "url": "https://example.org/alias.pdf",
            "model": "other",
            "instructions": "try again",
        },
        "identity",
    )
    assert decisions.read(tmp_path, alias) == decision
    assert alias.model_copy(update={"policy_revision": 3}).key != alias.key
    assert alias.model_copy(update={"section_ids": ["p2"]}).key != alias.key
    assert decisions.EvidenceRejected(decision, reused=True).result()["reused"] is True


def test_same_materialized_draft_reuses_negative_review_but_new_claims_change_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A final rejected review stays rejected without provider access or another roll."""
    monkeypatch.setenv("MINERVA_IDEAS_ROOT", str(tmp_path))
    run: dict = {"id": UUID(int=1), "issue_date": date(2026, 10, 14)}
    row: dict = {"company": "Acme", "fund": "Harbor Fund", "symbol": "ACME US"}
    document: dict = {"sha256": "b" * 64, "url": "https://example.com/original.pdf"}
    folder: Path = store.run_folder(run)
    store.json_artifact(
        folder,
        f"research/documents/{document['sha256']}.json",
        [{"id": "p1", "text": "Acme pricing power."}],
    )
    draft: View = View(
        instrument="equity",
        stance="bull",
        action="not stated",
        claims=[Claim(text="Acme will grow 500%.", passages=["p1.1"])],
        gap="",
    )
    rejected: decisions.EvidenceDecision
    reused: bool
    reused_again: bool
    again: decisions.EvidenceDecision
    rejected, reused = review_proposal(
        row, run, document, draft, model="unavailable-model"
    )
    again, reused_again = review_proposal(
        row,
        run,
        {**document, "url": "https://example.org/alias.pdf"},
        draft,
        model="different-unavailable-model",
    )
    assert rejected.outcome == again.outcome == "rejected"
    assert rejected.reason == again.reason
    assert reused is False and reused_again is True
    assert rejected.basis.key == again.basis.key
    assert decisions.read(folder, rejected.basis) == rejected
    assert (
        rejected.basis.model_copy(update={"proposal_sha256": "c" * 64}).key
        != rejected.basis.key
    )


def test_rejected_source_is_not_retried_without_new_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A different URL or unavailable model cannot reroll a frozen rejection."""
    from harness.ideas.research import assess

    monkeypatch.setenv("MINERVA_IDEAS_ROOT", str(tmp_path))
    run: dict = {"id": UUID(int=2), "issue_date": date(2026, 10, 14)}
    row: dict = {"company": "Acme", "fund": "Harbor Fund", "symbol": "ACME US"}
    document: dict = {"sha256": "d" * 64, "url": "https://example.com/original.pdf"}
    evidence: decisions.EvidenceBasis = decisions.basis(row, run, document, "identity")
    decisions.save(
        store.run_folder(run),
        decisions.EvidenceDecision(
            basis=evidence,
            outcome="rejected",
            reason="Wrong fund",
            document=document,
            result={},
        ),
    )
    with pytest.raises(decisions.EvidenceRejected) as failure:
        assess(
            row,
            run,
            {**document, "url": "https://example.org/alias.pdf"},
            model="unavailable-model",
        )
    assert failure.value.reused is True
    assert failure.value.decision.basis.key == evidence.key


def test_equivalent_proposal_formatting_reuses_the_stored_canonical_draft(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Claim order, whitespace, notes and duplicate passage IDs are not new evidence."""
    monkeypatch.setenv("MINERVA_IDEAS_ROOT", str(tmp_path))
    run: dict = {"id": UUID(int=3), "issue_date": date(2026, 10, 14)}
    row: dict = {"company": "Acme", "fund": "Harbor Fund", "symbol": "ACME US"}
    document: dict = {"sha256": "e" * 64, "url": "https://example.com/original.pdf"}
    store.json_artifact(
        store.run_folder(run),
        f"research/documents/{document['sha256']}.json",
        [
            {"id": "p1", "text": "Acme has pricing power."},
            {"id": "p2", "text": "Acme has resilient demand."},
        ],
    )
    first: View = View(
        instrument="equity",
        stance="bull",
        action="not stated",
        claims=[
            Claim(text="Acme grows 500%.", passages=["p1.1", "p2.1"]),
            Claim(text="Acme grows 900%.", passages=["p2.1"]),
        ],
        gap="first notes",
    )
    changed: View = first.model_copy(
        update={
            "claims": [
                first.claims[1],
                Claim(text=" Acme   grows 500%. ", passages=["p2.1", "p1.1", "p1.1"]),
            ],
            "gap": "different notes",
        }
    )
    initial: decisions.EvidenceDecision
    initial_reused: bool
    repeated: decisions.EvidenceDecision
    reused: bool
    initial, initial_reused = review_proposal(
        row, run, document, first, model="unavailable-model"
    )
    repeated, reused = review_proposal(row, run, document, changed, model="other-model")
    assert initial_reused is False
    assert reused is True
    assert repeated == initial
    assert repeated.result["draft"]["gap"] == "first notes"
    assert repeated.result["draft"]["claims"][0]["passages"] == ["p1.1", "p2.1"]


def test_rejected_explicit_revision_preserves_a_ready_approval_without_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unsuccessful replacement cannot clear a previously approved row."""
    from harness.ideas.extraction import apply_decision

    monkeypatch.delenv("MINERVA_DATABASE_URL", raising=False)
    proposal: View = View(
        instrument="equity",
        stance="bull",
        action="not stated",
        claims=[Claim(text="Unsupported 500%.", passages=["p1.1"])],
        gap="",
    )
    evidence: decisions.EvidenceBasis = decisions.EvidenceBasis(
        source_sha256="f" * 64,
        company="acme",
        fund="harbor",
        symbol="ACME",
        issue_date=date(2026, 10, 14),
        section_ids=[],
        anchor_ids=[],
        stage="claims",
    )
    decision: decisions.EvidenceDecision = decisions.EvidenceDecision(
        basis=evidence,
        outcome="rejected",
        reason="Unsupported number",
        document={},
        result={"draft": proposal.model_dump(mode="json"), "review": None},
    )
    result: dict = apply_decision(
        UUID(int=4), 1, decision, reused=True, preserve_ready=True
    )
    assert result["outcome"] == "claim_revision_required"
    assert result["preserved_ready"] is True
    assert result["reused"] is True


def test_same_bytes_reuse_the_first_approved_original_citation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unverified alias cannot replace the approved original's provenance."""
    from harness.ideas.research import approved_document, assess

    monkeypatch.setenv("MINERVA_IDEAS_ROOT", str(tmp_path))
    run: dict = {"id": UUID(int=5), "issue_date": date(2026, 10, 14)}
    row: dict = {"company": "Acme", "fund": "Harbor Fund", "symbol": "ACME US"}
    approved: EvidenceIdentity = identity("Harbor Fund", "Harbor Capital", "specific")
    document: dict = {
        "sha256": "1" * 64,
        "url": "https://example.com/manager-original.pdf",
        "identity": approved.model_dump(mode="json"),
    }
    evidence: decisions.EvidenceBasis = decisions.basis(row, run, document, "identity")
    decisions.save(
        store.run_folder(run),
        decisions.EvidenceDecision(
            basis=evidence,
            outcome="accepted",
            reason="Original approved",
            document=document,
            result=approved.model_dump(mode="json"),
        ),
    )
    alias: dict = {
        "sha256": document["sha256"],
        "url": "https://example.org/unverified-alias.pdf",
    }
    assert assess(row, run, alias, model="unavailable-model") == approved
    assert approved_document(row, run, alias) == document


def test_provider_configuration_failure_is_not_negative_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A provider failure remains retryable and cannot freeze an evidence rejection."""
    from harness.ideas.model import ModelError
    from harness.ideas.research import assess

    monkeypatch.setenv("MINERVA_IDEAS_ROOT", str(tmp_path))
    run: dict = {"id": UUID(int=6), "issue_date": date(2026, 10, 14)}
    row: dict = {"company": "Acme", "fund": "Harbor Fund", "symbol": "ACME US"}
    document: dict = {"sha256": "2" * 64, "url": "https://example.com/original.pdf"}
    folder: Path = store.run_folder(run)
    store.json_artifact(
        folder,
        f"research/documents/{document['sha256']}.json",
        [{"id": "p1", "text": "Harbor Fund Q2 2026. Acme has pricing power."}],
    )
    with pytest.raises(ModelError):
        assess(row, run, document, model="unsupported-provider-model")
    assert (
        decisions.read(folder, decisions.basis(row, run, document, "identity")) is None
    )


def test_metadata_errors_can_be_repaired_but_policy_errors_remain_final() -> None:
    """Only invalid references or own-block wording qualify for metadata correction."""
    from harness.ideas.research import MetadataError

    parts: list[dict[str, str]] = [
        {"id": "p1", "text": "Harbor Capital Q2 2026"},
        {"id": "p2", "text": "Harbor Global Fund"},
        {"id": "p3", "text": "Acme has pricing power."},
    ]
    broken: EvidenceIdentity = identity(
        "Harbor Global Fund", "Harbor Capital", "specific"
    )
    broken.publisher_block = "missing"
    with pytest.raises(MetadataError):
        validate(broken, "Harbor Global Fund", parts)
    wrong: EvidenceIdentity = identity(
        "Harbor Global Fund", "Harbor Capital", "specific"
    )
    with pytest.raises(ValueError) as rejected:
        validate(wrong, "Harbor Sustainable Global Fund", parts)
    assert not isinstance(rejected.value, MetadataError)


@pytest.mark.parametrize(
    ("name", "ticker", "combined", "source_label"),
    [
        ("Polaris", "PII", "Polaris (PII)", "Polaris (PII)"),
        (
            "Builders FirstSource",
            "BLDR",
            "Builders FirstSource (NYSE:BLDR)",
            "Builders FirstSource (NYSE: BLDR)",
        ),
    ],
)
def test_matching_source_issuer_ticker_composite_requires_metadata_repair(
    name: str,
    ticker: str,
    combined: str,
    source_label: str,
) -> None:
    """Correct paired source identities need one field correction, not a new alias."""
    from harness.ideas.research import MetadataError

    parts: list[dict[str, str]] = [
        {"id": "p1", "text": "Harbor Capital Q2 2026"},
        {"id": "p2", "text": "Harbor Global Fund"},
        {"id": "p3", "text": source_label + " has pricing power."},
    ]
    candidate: EvidenceIdentity = identity(
        "Harbor Global Fund", "Harbor Capital", "specific"
    )
    candidate.company = combined
    row: dict[str, str] = {
        "company": name,
        "fund": "Harbor Global Fund",
        "symbol": ticker + " US",
    }
    with pytest.raises(MetadataError, match="never a combined"):
        validate_match(
            resolve_identity(candidate.model_dump(), parts),
            parts,
            date(2026, 10, 14),
            row,
        )
    candidate.company = name
    validate_match(
        resolve_identity(candidate.model_dump(), parts), parts, date(2026, 10, 14), row
    )


@pytest.mark.parametrize(
    ("combined", "source_label"),
    [
        ("Other Acme (ACME)", "Other Acme (ACME)"),
        ("Acme (OTHER)", "Acme (OTHER)"),
        ("Acme (ACME)", "Acme has pricing power, with no matching ticker pair"),
    ],
)
def test_wrong_composite_issuer_ticker_or_missing_source_pair_is_final(
    combined: str,
    source_label: str,
) -> None:
    """Metadata repair cannot authorize another issuer, ticker or unsupported pair."""
    from harness.ideas.research import MetadataError

    parts: list[dict[str, str]] = [
        {"id": "p1", "text": "Harbor Capital Q2 2026"},
        {"id": "p2", "text": "Harbor Global Fund"},
        {"id": "p3", "text": source_label + " has pricing power."},
    ]
    candidate: EvidenceIdentity = identity(
        "Harbor Global Fund", "Harbor Capital", "specific"
    )
    candidate.company = combined
    with pytest.raises(ValueError) as failure:
        validate(candidate, "Harbor Global Fund", parts)
    assert not isinstance(failure.value, MetadataError)
