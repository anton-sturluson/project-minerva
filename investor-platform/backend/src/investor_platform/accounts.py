"""Portfolio account contracts and ownership-scoped HTTP operations."""

from collections.abc import Sequence
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, StringConstraints
from sqlalchemy import Select, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from investor_platform.db import Actor, CurrentActor, DatabaseSession
from investor_platform.domain import Currency, FundingStatus
from investor_platform.models import Account, Workspace

router: APIRouter = APIRouter(prefix="/api")


class AccountInput(BaseModel):
    """User-supplied account identity and immutable base currency."""

    model_config = ConfigDict(extra="forbid")
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
    base_currency: Currency


class ReconstructionView(BaseModel):
    """Public import assumptions without private source rows or raw exports."""

    funding_status: FundingStatus = FundingStatus.INFERRED
    warning: str
    source_sha256: str
    imported_trades: int
    skipped: list[dict]
    opening_cash: str | None = None
    cash_method: str | None = None
    dividend_policy: Literal["unrecorded_zero"] | None = None
    opening_positions: dict[str, str]
    price_discrepancies: list[int]


class AccountView(AccountInput):
    """Stored account identity and its optional provisional reconstruction summary."""

    model_config = ConfigDict(from_attributes=True)
    id: UUID
    created_at: datetime
    reconstruction: ReconstructionView | None = None


def owned_account(
    session: Session, actor: Actor, account_id: UUID, *, lock: bool = False
) -> Account:
    """Resolve an account owned by this actor, optionally serializing its mutations."""
    query: Select[tuple[Account]] = (
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
    account: Account | None = session.scalar(query)
    if account is None:
        raise HTTPException(404, "Account not found")
    return account


@router.get("/accounts", response_model=list[AccountView])
def list_accounts(session: DatabaseSession, actor: CurrentActor) -> Sequence[Account]:
    """List this owner's accounts in a stable creation order."""
    return session.scalars(
        select(Account)
        .join(Workspace)
        .where(Workspace.id == actor.workspace_id, Workspace.owner_id == actor.owner_id)
        .order_by(Account.created_at, Account.id)
    ).all()


@router.post("/accounts", response_model=AccountView, status_code=201)
def create_account(data: AccountInput, session: DatabaseSession, actor: CurrentActor) -> Account:
    """Create a named account, accepting identical retries without another record."""
    workspace: Workspace | None = session.scalar(
        select(Workspace).where(
            Workspace.id == actor.workspace_id, Workspace.owner_id == actor.owner_id
        )
    )
    if workspace is None:
        raise HTTPException(403, "Workspace is unavailable")
    account: Account = Account(workspace_id=workspace.id, **data.model_dump())
    session.add(account)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        existing: Account | None = next(
            (a for a in list_accounts(session, actor) if a.name == data.name), None
        )
        if existing and existing.name == data.name and existing.base_currency == data.base_currency:
            return existing
        raise HTTPException(
            409, "A portfolio with this name already exists in this workspace"
        ) from None
    session.refresh(account)
    return account
