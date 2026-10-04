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
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


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
        UniqueConstraint("workspace_id", "name", name="account_workspace_name"),
        CheckConstraint("length(trim(name)) BETWEEN 1 AND 80", name="account_name"),
        CheckConstraint(
            "base_currency IN ('USD','EUR','GBP','CAD','AUD','JPY','CHF','HKD','SGD')",
            name="account_currency",
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id"))
    reconstruction: Mapped[dict | None] = mapped_column(JSONB)
    name: Mapped[str] = mapped_column(String(80))
    base_currency: Mapped[str] = mapped_column(String(3))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LedgerEntry(Base):
    __tablename__ = "ledger_entries"
    __table_args__ = (
        UniqueConstraint("account_id", "request_key", name="ledger_request_key"),
        CheckConstraint(
            "kind IN ('opening_cash','deposit','withdrawal','income','expense',"
            "'opening_position','transfer_in','buy','sell')",
            name="ledger_kind",
        ),
        CheckConstraint(
            "amount >= 0 AND (kind IN ('opening_cash','opening_position',"
            "'transfer_in','sell') OR amount > 0)",
            name="ledger_amount",
        ),
        CheckConstraint(
            """
      (kind IN ('opening_cash','deposit','withdrawal','income','expense') AND security_id IS NULL
        AND quantity IS NULL AND price IS NULL AND fees = 0 AND cost_basis IS NULL)
      OR (kind IN ('opening_position','transfer_in') AND security_id IS NOT NULL AND quantity > 0
        AND quantity IS NOT NULL AND price IS NULL AND fees = 0 AND amount = 0
        AND (cost_basis IS NULL OR cost_basis >= 0))
      OR (kind IN ('buy','sell') AND security_id IS NOT NULL AND quantity IS NOT NULL
        AND quantity > 0 AND price IS NOT NULL AND price > 0 AND fees >= 0 AND cost_basis IS NULL)
    """,
            name="entry_shape",
        ),
        Index("ledger_order", "account_id", "effective_date", "id"),
    )
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    account_id: Mapped[UUID] = mapped_column(ForeignKey("accounts.id"))
    kind: Mapped[str] = mapped_column(String(24))
    effective_date: Mapped[date] = mapped_column(Date)
    amount: Mapped[Decimal] = mapped_column(Numeric(48, 16))
    currency: Mapped[str] = mapped_column(String(3))
    note: Mapped[str] = mapped_column(String(240))
    created_by: Mapped[UUID] = mapped_column(ForeignKey("owners.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    request_key: Mapped[UUID]
    request_body: Mapped[str] = mapped_column(Text)

    security_id: Mapped[UUID | None] = mapped_column(ForeignKey("securities.id"))
    security: Mapped["Security | None"] = relationship()
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    price: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    fees: Mapped[Decimal] = mapped_column(Numeric(24, 8), default=Decimal(0), server_default="0")
    cost_basis: Mapped[Decimal | None] = mapped_column(Numeric(24, 8))


class Security(Base):
    __tablename__ = "securities"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "ticker", "exchange", "currency", name="security_identity"
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id"))
    ticker: Mapped[str] = mapped_column(String(20))
    exchange: Mapped[str] = mapped_column(String(12))
    currency: Mapped[str] = mapped_column(String(3))
    market_identity: Mapped[dict | None] = mapped_column(JSONB)


class MarketCache(Base):
    __tablename__ = "market_cache"
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id"), primary_key=True)
    provider: Mapped[str] = mapped_column(String(20), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(40), primary_key=True)
    start: Mapped[date] = mapped_column(Date)
    end: Mapped[date] = mapped_column(Date)
    payload: Mapped[dict] = mapped_column(JSONB)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class LedgerCorrection(Base):
    __tablename__ = "ledger_corrections"
    __table_args__ = (UniqueConstraint("account_id", "request_key"),)
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    account_id: Mapped[UUID] = mapped_column(ForeignKey("accounts.id"))
    original_id: Mapped[int] = mapped_column(ForeignKey("ledger_entries.id"), unique=True)
    replacement_id: Mapped[int | None] = mapped_column(ForeignKey("ledger_entries.id"), unique=True)
    reason: Mapped[str] = mapped_column(String(240))
    created_by: Mapped[UUID] = mapped_column(ForeignKey("owners.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    request_key: Mapped[UUID]
    request_body: Mapped[str] = mapped_column(Text)
