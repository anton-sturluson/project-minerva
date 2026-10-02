from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, StringConstraints
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .db import Actor, get_actor, get_session
from .models import Account, Workspace

router = APIRouter(prefix="/api")
DB = Annotated[Session, Depends(get_session)]
Identity = Annotated[Actor, Depends(get_actor)]
Currency = Literal["USD", "EUR", "GBP", "CAD", "AUD", "JPY", "CHF", "HKD", "SGD"]


class AccountInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
    base_currency: Currency


class AccountView(AccountInput):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    created_at: datetime


def owned_account(session, actor, account_id, *, lock=False):
    query = (
        select(Account)
        .join(Workspace)
        .where(
            Account.id == account_id,
            Workspace.id == actor.workspace_id,
            Workspace.owner_id == actor.owner_id,
        )
    )
    if lock:
        query = query.with_for_update(of=Account)
    account = session.scalar(query)
    if account is None:
        raise HTTPException(404, "Account not found")
    return account


@router.get("/account", response_model=AccountView | None)
def current_account(session: DB, actor: Identity):
    return session.scalar(
        select(Account)
        .join(Workspace)
        .where(Workspace.id == actor.workspace_id, Workspace.owner_id == actor.owner_id)
    )


@router.get("/accounts/{account_id}", response_model=AccountView)
def read_account(account_id: UUID, session: DB, actor: Identity):
    return owned_account(session, actor, account_id)


@router.post("/account", response_model=AccountView, status_code=201)
def create_account(data: AccountInput, session: DB, actor: Identity):
    workspace = session.scalar(
        select(Workspace).where(
            Workspace.id == actor.workspace_id, Workspace.owner_id == actor.owner_id
        )
    )
    if workspace is None:
        raise HTTPException(403, "Workspace is unavailable")
    account = Account(workspace_id=workspace.id, **data.model_dump())
    session.add(account)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        existing = current_account(session, actor)
        if existing and existing.name == data.name and existing.base_currency == data.base_currency:
            return existing
        raise HTTPException(409, "This workspace already has an account") from None
    session.refresh(account)
    return account
