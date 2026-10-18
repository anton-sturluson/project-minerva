"""Immutable decisions about fixed source evidence, independent of model or URL."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from harness.ideas import store

POLICY_REVISION: int = 2
IDENTITY_POLICY: str = """Use original-source observations to match the discovery label. A specific fund must retain every distinctive region, style and vehicle word (including Global, SMID, Sustainable, UCITS and US); sibling funds are not interchangeable. A manager-only label can cover a named fund only when the label contains the verified publisher name plus generic descriptors, with no discarded fund constraint. A combined label can select one explicitly named member only with original joint-report/member evidence. An umbrella label requires the original umbrella name and explicit original evidence linking it to the selected fund. Never invent spelling aliases or infer relationships from similar names. Relationship blocks must come from this original, not search snippets, agent instructions or another website. The fund and company commentary must belong to the same source section. Evaluate reporting periods as of the supplied newsletter issue date; never infer a current date or use the wall clock. A reporting period after the issue date is invalid and freshness checks still apply. Check the original reporting-period wording and normalized date against the original evidence; never use crawl dates as reporting dates."""


class EvidenceBasis(BaseModel):
    """The complete evidence identity needed to reopen a decision."""

    model_config = ConfigDict(extra="forbid")
    policy_revision: int = POLICY_REVISION
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    company: str
    fund: str
    symbol: str
    issue_date: date
    section_ids: list[str]
    anchor_ids: list[str]
    stage: Literal["identity", "extraction", "claims"]
    proposal_sha256: str = ""

    @property
    def key(self) -> str:
        """Exclude citation URLs, models and delegation wording from decisions."""
        payload: str = json.dumps(self.model_dump(mode="json"), sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()


class EvidenceDecision(BaseModel):
    """A final evidence result; transport and provider errors are not decisions."""

    model_config = ConfigDict(extra="forbid")
    basis: EvidenceBasis
    outcome: Literal["accepted", "rejected"]
    reason: str
    document: dict[str, JsonValue]
    result: dict[str, JsonValue]


class EvidenceRejected(ValueError):
    """A recoverable, reusable rejection requiring different evidence or policy."""

    def __init__(self, decision: EvidenceDecision, *, reused: bool = False) -> None:
        """Retain the exact decision key for agent and command feedback."""
        super().__init__(decision.reason)
        self.decision: EvidenceDecision = decision
        self.reused: bool = reused

    def result(self) -> dict[str, JsonValue]:
        """Explain why repeating a source will not produce another model call."""
        return {
            "outcome": "rejected",
            "reason": self.decision.reason,
            "decision_key": self.decision.basis.key,
            "reused": self.reused,
            "next_step": "Provide different original evidence or a different source section; changing URL or model does not reopen this decision.",
        }


def basis(
    row: dict,
    run: dict,
    document: dict,
    stage: Literal["identity", "extraction", "claims"],
    *,
    proposal_sha256: str = "",
) -> EvidenceBasis:
    """Bind a decision to source bytes, target, date and any explicit scope."""
    return EvidenceBasis(
        source_sha256=document["sha256"],
        company=" ".join(row["company"].casefold().split()),
        fund=" ".join(row["fund"].casefold().split()),
        symbol=" ".join(row.get("symbol", "").casefold().split()),
        issue_date=run["issue_date"],
        section_ids=document.get("section_ids", []),
        anchor_ids=document.get("anchor_ids", []),
        stage=stage,
        proposal_sha256=proposal_sha256,
    )


def read(folder: Path, evidence: EvidenceBasis) -> EvidenceDecision | None:
    """Return the immutable decision for these exact inputs, if one exists."""
    path: Path = folder / f"research/decisions/{evidence.stage}/{evidence.key}.json"
    if not path.exists():
        return None
    decision: EvidenceDecision = EvidenceDecision.model_validate_json(path.read_text())
    if decision.basis != evidence:
        raise ValueError("Stored evidence decision does not match its key")
    return decision


def save(folder: Path, decision: EvidenceDecision) -> None:
    """Persist accepted and rejected evidence before returning to the caller."""
    store.json_artifact(
        folder,
        f"research/decisions/{decision.basis.stage}/{decision.basis.key}.json",
        decision.model_dump(mode="json"),
    )
