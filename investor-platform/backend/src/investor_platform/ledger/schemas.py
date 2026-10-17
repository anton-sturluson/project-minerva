"""Ledger request and response contracts."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PlainSerializer,
    StringConstraints,
    field_validator,
    model_validator,
)

from investor_platform.domain import (
    IN_KIND_ENTRIES,
    MARKET_TIMEZONE,
    Currency,
    EntryKind,
    IncomeKind,
)

Money = Annotated[Decimal, Field(ge=0, max_digits=24, decimal_places=8, allow_inf_nan=False)]


class EntryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: UUID
    effective_date: date
    currency: Currency
    note: str = Field(default="", max_length=240)

    @field_validator("effective_date")
    @classmethod
    def no_future(cls, value):
        if value > datetime.now(MARKET_TIMEZONE).date():
            raise ValueError("Posted entries cannot be future dated (New York)")
        return value


class CashInput(EntryInput):
    kind: Literal[
        EntryKind.OPENING_CASH,
        EntryKind.DEPOSIT,
        EntryKind.WITHDRAWAL,
        EntryKind.INCOME,
        EntryKind.EXPENSE,
    ]
    amount: Money
    income_kind: IncomeKind | None = None
    income_security_id: UUID | None = None
    accrual_date: date | None = None

    @model_validator(mode="after")
    def positive_amount(self):
        if self.kind != EntryKind.OPENING_CASH and self.amount <= 0:
            raise ValueError("Cash entries other than opening cash must be positive")
        if self.kind != EntryKind.INCOME and any(
            value is not None
            for value in (self.income_kind, self.income_security_id, self.accrual_date)
        ):
            raise ValueError("Income attribution is only valid for investment income")
        if self.income_kind == IncomeKind.DIVIDEND:
            if self.income_security_id is None or self.accrual_date is None:
                raise ValueError("Dividends require a security and ex-dividend date")
            if self.accrual_date > self.effective_date:
                raise ValueError("Ex-dividend date must be on or before the cash payment date")
        elif self.income_kind in {IncomeKind.INTEREST, IncomeKind.OTHER}:
            if self.accrual_date is not None:
                raise ValueError("Only dividends use an ex-dividend date")
        elif self.income_security_id is not None or self.accrual_date is not None:
            raise ValueError("Classify income before linking a security")
        return self


WireDecimal = Annotated[Decimal, PlainSerializer(lambda value: format(value, "f"), return_type=str)]


class SecurityView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    ticker: str
    exchange: str
    currency: Currency
    market_identity: dict | None = Field(default=None, exclude=True)


class HoldingView(BaseModel):
    security: SecurityView
    quantity: WireDecimal
    cost_basis: WireDecimal | None


class EntryView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    kind: EntryKind
    effective_date: date
    amount: WireDecimal
    currency: Currency
    note: str
    created_by: UUID
    created_at: datetime
    security: SecurityView | None = None
    income_kind: IncomeKind | None = None
    income_security: SecurityView | None = None
    accrual_date: date | None = None
    quantity: WireDecimal | None = None
    price: WireDecimal | None = None
    fees: WireDecimal = Decimal(0)
    cost_basis: WireDecimal | None = None
    realized_pnl: WireDecimal | None = None


class CorrectionView(BaseModel):
    id: int
    original: EntryView
    replacement: EntryView | None
    reason: str
    created_by: UUID
    created_at: datetime


class LedgerView(BaseModel):
    currency: Currency
    balance: WireDecimal
    entries: list[EntryView]
    holdings: list[HoldingView] = []
    corrections: list[CorrectionView] = []


Quantity = Annotated[Decimal, Field(gt=0, max_digits=20, decimal_places=8, allow_inf_nan=False)]


class TradeInput(EntryInput):
    kind: Literal[EntryKind.OPENING_POSITION, EntryKind.TRANSFER_IN, EntryKind.BUY, EntryKind.SELL]
    ticker: Annotated[
        str,
        StringConstraints(pattern=r"^[A-Z0-9][A-Z0-9.\-]{0,19}$"),
    ]
    exchange: Annotated[
        str,
        StringConstraints(pattern=r"^[A-Z0-9][A-Z0-9_\-]{1,11}$"),
    ]
    quantity: Quantity
    price: Quantity | None = None
    fees: Money = Decimal(0)
    cost_basis: Money | None = None

    @field_validator("ticker", "exchange", mode="before")
    @classmethod
    def normalize_identity(cls, value):
        return value.strip().upper() if isinstance(value, str) else value

    @model_validator(mode="after")
    def valid_trade(self):
        if self.kind in IN_KIND_ENTRIES:
            if self.price is not None or self.fees != 0:
                raise ValueError(
                    "Received shares use optional total cost basis, not a price or fee"
                )
        elif self.price is None or self.cost_basis is not None:
            raise ValueError(
                "Trades require a price and cannot override their calculated cost basis"
            )
        return self
