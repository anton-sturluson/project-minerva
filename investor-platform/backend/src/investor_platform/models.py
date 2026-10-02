from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Owner(Base):
    __tablename__ = "owners"
    id: Mapped[UUID] = mapped_column(primary_key=True)


class Workspace(Base):
    __tablename__ = "workspaces"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("owners.id"), unique=True)


class Account(Base):
    __tablename__ = "accounts"
    __table_args__ = (
        UniqueConstraint("workspace_id"),
        CheckConstraint("length(trim(name)) BETWEEN 1 AND 80", name="account_name"),
        CheckConstraint(
            "base_currency IN ('USD','EUR','GBP','CAD','AUD','JPY','CHF','HKD','SGD')",
            name="account_currency",
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id"))
    name: Mapped[str] = mapped_column(String(80))
    base_currency: Mapped[str] = mapped_column(String(3))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LedgerEntry(Base):
    __tablename__ = "ledger_entries"
    __table_args__ = (
        UniqueConstraint("account_id", "request_key", name="ledger_request_key"),
        CheckConstraint("kind IN ('opening_cash','deposit','withdrawal')", name="ledger_kind"),
        CheckConstraint(
            "amount >= 0 AND (kind = 'opening_cash' OR amount > 0)", name="ledger_amount"
        ),
        Index("ledger_order", "account_id", "effective_date", "id"),
        Index(
            "one_opening_cash",
            "account_id",
            unique=True,
            postgresql_where=text("kind = 'opening_cash'"),
        ),
    )
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    account_id: Mapped[UUID] = mapped_column(ForeignKey("accounts.id"))
    kind: Mapped[str] = mapped_column(String(24))
    effective_date: Mapped[date] = mapped_column(Date)
    amount: Mapped[Decimal] = mapped_column(Numeric(24, 8))
    currency: Mapped[str] = mapped_column(String(3))
    note: Mapped[str] = mapped_column(String(240))
    created_by: Mapped[UUID] = mapped_column(ForeignKey("owners.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    request_key: Mapped[UUID]
    request_body: Mapped[str] = mapped_column(Text)
