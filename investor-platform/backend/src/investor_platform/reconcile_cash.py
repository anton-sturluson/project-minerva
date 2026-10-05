"""Preview and atomically replace an imported portfolio's cash history from reviewed evidence."""

import argparse
import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid5

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .accounting import replay
from .accounts import owned_account
from .db import LOCAL_OWNER, LOCAL_WORKSPACE, Actor, make_engine
from .domain import MARKET_TIMEZONE, EntryKind, FundingStatus
from .ledger import CashInput, Money, build_cash, entries_for, fingerprint, ledger_view
from .models import LedgerCorrection


class CashReconciliation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: UUID
    source_reference: str = Field(min_length=1, max_length=240)
    as_of: date
    reported_cash: Money
    remove_entry_ids: list[int] = Field(max_length=5000)
    entries: list[CashInput] = Field(min_length=1, max_length=5000)
    confirm_complete_funding: bool = False
    expected_revision: str | None = None

    @model_validator(mode="after")
    def unique_records(self):
        if self.as_of > datetime.now(MARKET_TIMEZONE).date():
            raise ValueError("The closing cash checkpoint cannot be in the future")
        if len(set(self.remove_entry_ids)) != len(self.remove_entry_ids):
            raise ValueError("Cash entries to replace must be unique")
        if len({e.request_key for e in self.entries}) != len(self.entries):
            raise ValueError("Each source cash row needs a unique request key")
        if any(e.effective_date > self.as_of for e in self.entries):
            raise ValueError("Cash entries cannot follow the closing balance checkpoint")
        if any(e.kind == EntryKind.OPENING_CASH for e in self.entries):
            raise ValueError(
                "Use dated deposits for initial funding, not a new inferred opening balance"
            )
        return self


def reconcile(engine, account_id, plan, *, apply=False, actor=None):
    actor = actor or Actor(LOCAL_OWNER, LOCAL_WORKSPACE)
    body = plan.model_dump(mode="json", exclude={"expected_revision"})
    digest = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
    key = str(plan.request_key)
    with Session(engine) as session:
        account = owned_account(session, actor, account_id, lock=True)
        if not account.reconstruction:
            raise ValueError(
                "This workflow is for imported portfolios; use ordinary ledger corrections"
            )
        receipts = account.reconstruction.get("cash_reconciliations", {})
        previous = receipts.get(key)
        if previous:
            if previous["digest"] != digest:
                raise ValueError("This reconciliation key was already used for a different plan")
            return previous["result"] | {"already_applied": True}
        before = entries_for(session, account_id)
        revision = hashlib.sha256(
            json.dumps(
                {"ids": [e.id for e in before], "receipts": receipts}, sort_keys=True
            ).encode()
        ).hexdigest()
        if apply and plan.expected_revision != revision:
            raise ValueError("Records changed or were not previewed; preview this plan again")
        cash_ids = {e.id for e in before if e.security_id is None}
        if set(plan.remove_entry_ids) != cash_ids:
            raise ValueError(
                "The plan must explicitly replace every active cash record, and no trades"
            )
        if before and plan.as_of < max(e.effective_date for e in before):
            raise ValueError("The closing cash checkpoint must cover every current ledger entry")
        old = ledger_view(before, account.base_currency)
        for entry_id in plan.remove_entry_ids:
            session.add(
                LedgerCorrection(
                    account_id=account_id,
                    original_id=entry_id,
                    replacement_id=None,
                    created_by=actor.owner_id,
                    request_key=uuid5(plan.request_key, f"void:{entry_id}"),
                    request_body=json.dumps({"reconciliation": key, "digest": digest}),
                    reason="Replace imported cash history: " + plan.source_reference[:200],
                )
            )
        for item in plan.entries:
            session.add(build_cash(account, item, session, actor, fingerprint(item)))
        session.flush()
        after = entries_for(session, account_id)
        updated = ledger_view(after, account.base_currency)
        if updated.holdings != old.holdings:
            raise ValueError("Cash reconciliation cannot change holdings or cost basis")
        balance = replay([e for e in after if e.effective_date <= plan.as_of])[0]
        if balance.quantize(Decimal(".01")) != plan.reported_cash.quantize(Decimal(".01")):
            raise ValueError(
                f"Closing cash does not reconcile: computed {balance:.2f}, "
                f"reported {plan.reported_cash:.2f}"
            )
        result = {
            "account_id": str(account_id),
            "revision": revision,
            "as_of": str(plan.as_of),
            "previous_cash": str(old.balance),
            "cash": str(balance),
            "removed_cash_entries": len(plan.remove_entry_ids),
            "new_cash_entries": len(plan.entries),
            "holdings_unchanged": True,
            "funding_confirmed": plan.confirm_complete_funding,
        }
        if not apply:
            session.rollback()
            return result | {"applied": False}
        status = (
            FundingStatus.RECONCILED if plan.confirm_complete_funding else FundingStatus.INFERRED
        )
        result = result | {"applied": True}
        receipts = receipts | {key: {"digest": digest, "source": body, "result": result}}
        account.reconstruction = account.reconstruction | {
            "funding_status": status,
            "cash_reconciliations": receipts,
        }
        session.commit()
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--account", type=UUID, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    engine = make_engine()
    try:
        plan = CashReconciliation.model_validate_json(args.plan.read_text())
        print(json.dumps(reconcile(engine, args.account, plan, apply=args.apply), indent=2))
    except (ValueError, OSError, HTTPException) as exc:
        parser.exit(1, f"Reconciliation stopped: {getattr(exc, 'detail', str(exc))}\n")
    except SQLAlchemyError:
        parser.exit(
            1,
            "Reconciliation stopped: the database rejected the plan; no changes were committed.\n",
        )
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
