"""Construct validated cash and trade entries without committing them."""

from decimal import Decimal, localcontext

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from investor_platform.domain import ACCOUNTING_PRECISION, IN_KIND_ENTRIES, EntryKind
from investor_platform.models import LedgerEntry, Security


def build_cash(account, data, session, actor, body):
    if data.currency != account.base_currency:
        raise HTTPException(422, "Entry currency must match the account")
    if data.income_security_id is not None:
        security = session.scalar(
            select(Security).where(
                Security.id == data.income_security_id,
                Security.workspace_id == actor.workspace_id,
            )
        )
        if security is None:
            raise HTTPException(404, "Income security not found")
    return LedgerEntry(
        account_id=account.id, created_by=actor.owner_id, request_body=body, **data.model_dump()
    )


def build_trade(account, data, session, actor, body):
    account_id = account.id
    if data.currency != account.base_currency:
        raise HTTPException(422, "Security currency must match the account")
    identity = {
        "workspace_id": actor.workspace_id,
        "ticker": data.ticker,
        "exchange": data.exchange,
        "currency": data.currency,
    }
    query = select(Security).filter_by(**identity)
    security = session.scalar(query)
    if security is None:
        # Different accounts may create the same workspace-wide identity concurrently.
        session.execute(
            insert(Security)
            .values(**identity)
            .on_conflict_do_nothing(constraint="security_identity")
        )
        security = session.scalar(query)
    with localcontext() as context:
        context.prec = ACCOUNTING_PRECISION
        amount = Decimal(0)
        if data.kind not in IN_KIND_ENTRIES:
            gross = data.quantity * data.price
            amount = gross + data.fees if data.kind == EntryKind.BUY else gross - data.fees
            if amount < 0:
                raise HTTPException(422, "Sale fees cannot exceed proceeds")
    return LedgerEntry(
        account_id=account_id,
        security_id=security.id,
        created_by=actor.owner_id,
        request_body=body,
        amount=amount,
        **data.model_dump(exclude={"ticker", "exchange"}),
    )
