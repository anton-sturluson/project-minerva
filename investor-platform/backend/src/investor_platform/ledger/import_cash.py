"""Preview or atomically append reviewed income and expenses to an imported account."""

import argparse
import hashlib
import json
import sys
from decimal import Context, Decimal, localcontext
from pathlib import Path
from typing import Self, cast
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from investor_platform.accounts import owned_account
from investor_platform.db import LOCAL_OWNER, LOCAL_WORKSPACE, Actor, make_engine
from investor_platform.domain import ACCOUNTING_PRECISION, EntryKind
from investor_platform.ledger.commands import build_cash
from investor_platform.ledger.purchase_funding import funding_revision, sync_canonical_funding
from investor_platform.ledger.schemas import CashInput, LedgerRecord, LedgerView
from investor_platform.ledger.state import (
    active_entries_for_account,
    fingerprint,
    funding_purchase_key,
    ledger_snapshot,
    ledger_view,
)
from investor_platform.models import Account, LedgerCorrection, LedgerEntry


class CashImport(BaseModel):
    """Broker-neutral reviewed cash events with stable batch and source-event keys."""

    model_config = ConfigDict(extra="forbid")
    request_key: UUID
    source_reference: str = Field(min_length=1, max_length=240)
    entries: list[CashInput] = Field(min_length=1, max_length=5000)
    expected_revision: str | None = None

    @model_validator(mode="after")
    def valid_events(self) -> Self:
        """Require distinct source events and limit this additive import to income and costs."""
        if len({entry.request_key for entry in self.entries}) != len(self.entries):
            raise ValueError(
                "Duplicate source-event keys; give each cash event a stable unique UUID"
            )
        if any(entry.kind not in {EntryKind.INCOME, EntryKind.EXPENSE} for entry in self.entries):
            raise ValueError(
                "Only income and expense are supported; use ledger workflows for funding"
            )
        return self


def inferred_total(entries: list[LedgerEntry]) -> Decimal:
    """Sum only deposits with explicit canonical purchase-funding provenance."""
    return sum((entry.amount for entry in entries if funding_purchase_key(entry)), Decimal(0))


def import_cash(
    engine: Engine,
    account_id: UUID,
    plan: CashImport,
    *,
    apply: bool = False,
    actor: Actor | None = None,
) -> LedgerRecord:
    """Append missing events once, recalculate funding once, and preserve all trades atomically."""
    actor = actor or Actor(LOCAL_OWNER, LOCAL_WORKSPACE)
    body: LedgerRecord = plan.model_dump(mode="json", exclude={"expected_revision"})
    digest: str = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
    key: str = str(plan.request_key)
    session: Session
    context: Context
    with Session(engine) as session, localcontext() as context:
        context.prec = ACCOUNTING_PRECISION
        account: Account = owned_account(session, actor, account_id, lock=True)
        if not account.reconstruction:
            raise ValueError(
                "Cash import requires an existing imported account; select that account"
            )
        receipts: dict[str, LedgerRecord] = cast(
            dict[str, LedgerRecord], account.reconstruction.get("cash_imports", {})
        )
        previous: LedgerRecord | None = receipts.get(key)
        if previous is not None:
            if previous["digest"] != digest:
                raise ValueError(
                    "Batch key already used for a different plan; review a new batch key"
                )
            return cast(LedgerRecord, previous["result"]) | {"already_applied": True}
        before: list[LedgerEntry]
        history: dict[int, LedgerEntry]
        corrections: list[LedgerCorrection]
        before, history, corrections = ledger_snapshot(session, account_id)
        revision: str = hashlib.sha256(
            json.dumps(
                {"ledger_revision": funding_revision(account, before), "plan_digest": digest},
                sort_keys=True,
            ).encode()
        ).hexdigest()
        if apply and plan.expected_revision != revision:
            raise ValueError(
                "Records or plan changed, or preview is missing; preview again and copy revision"
            )
        old: LedgerView = ledger_view(before, account.base_currency)
        active_ids: set[int] = {entry.id for entry in before}
        corrected_ids: set[int] = {correction.original_id for correction in corrections} | {
            correction.replacement_id
            for correction in corrections
            if correction.replacement_id is not None
        }
        by_key: dict[UUID, LedgerEntry] = {entry.request_key: entry for entry in history.values()}
        added: int = 0
        skipped: int = 0
        item: CashInput
        for item in plan.entries:
            existing: LedgerEntry | None = by_key.get(item.request_key)
            if existing is not None:
                if existing.id not in active_ids or existing.id in corrected_ids:
                    raise ValueError(
                        "Source-event key belongs to a corrected record; review its ledger history"
                    )
                actual: CashInput = CashInput.model_validate(
                    {field: getattr(existing, field) for field in CashInput.model_fields}
                )
                if fingerprint(actual) != fingerprint(item):
                    raise ValueError(
                        "Source-event key already has different values; review its ledger history"
                    )
                skipped += 1
                continue
            session.add(build_cash(account, item, session, actor, fingerprint(item)))
            added += 1
        session.flush()
        sync_canonical_funding(session, account, actor, plan.request_key)
        after: list[LedgerEntry] = active_entries_for_account(session, account_id)
        updated: LedgerView = ledger_view(after, account.base_currency)
        trade_ids_before: list[int] = [
            entry.id for entry in before if entry.security_id is not None
        ]
        trade_ids_after: list[int] = [entry.id for entry in after if entry.security_id is not None]
        if updated.holdings != old.holdings or trade_ids_before != trade_ids_after:
            raise ValueError("Cash import changed holdings or trades; stop and inspect the plan")
        result: LedgerRecord = {
            "account_id": str(account_id),
            "revision": revision,
            "applied": apply,
            "already_applied": False,
            "previous_cash": str(old.balance),
            "cash": str(updated.balance),
            "previous_inferred_deposits_total": str(inferred_total(before)),
            "inferred_deposits_total": str(inferred_total(after)),
            "added_entries": added,
            "skipped_entries": skipped,
            "unresolved_income_count": sum(
                entry.kind == EntryKind.INCOME and entry.income_kind is None for entry in after
            ),
            "holdings_unchanged": True,
            "trades_unchanged": True,
        }
        if not apply:
            session.rollback()
            return result
        account.reconstruction = account.reconstruction | {
            "cash_imports": receipts | {key: {"digest": digest, "plan": body, "result": result}}
        }
        session.commit()
        return result


def main() -> None:
    """Print a JSON preview by default; apply only a plan pinned to its preview revision."""
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        description=__doc__,
        epilog="Example: investor-import-cash --account UUID --plan reviewed-cash.json",
    )
    parser.add_argument(
        "--account", type=UUID, required=True, help="Existing imported account UUID"
    )
    parser.add_argument("--plan", type=Path, required=True, help="Reviewed UTF-8 JSON cash plan")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Commit the whole plan; requires expected_revision in JSON",
    )
    if len(sys.argv) == 1:
        parser.print_help()
        return
    args: argparse.Namespace = parser.parse_args()
    engine: Engine = make_engine()
    try:
        plan: CashImport = CashImport.model_validate_json(args.plan.read_text(encoding="utf-8"))
        print(json.dumps(import_cash(engine, args.account, plan, apply=args.apply), indent=2))
    except (ValueError, OSError, HTTPException) as exc:
        parser.exit(1, f"Cash import stopped: {getattr(exc, 'detail', str(exc))}\n")
    except SQLAlchemyError:
        parser.exit(
            1, "Database rejected the plan; no changes committed. Preview again before retry.\n"
        )
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
