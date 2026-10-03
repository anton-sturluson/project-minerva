from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint, func
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
