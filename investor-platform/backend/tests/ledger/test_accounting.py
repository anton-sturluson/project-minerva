"""Check full and incremental FIFO accounting against independent expected balances."""

from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

from investor_platform.domain import EntryKind
from investor_platform.ledger.accounting import ReplayState, replay
from investor_platform.models import LedgerEntry


def entry(
    identifier: int,
    kind: EntryKind,
    amount: str,
    *,
    day: int = 2,
    security: UUID | None = None,
    quantity: str | None = None,
) -> LedgerEntry:
    """Build an isolated immutable source entry with exact numeric values."""
    return LedgerEntry(
        id=identifier,
        kind=kind,
        amount=Decimal(amount),
        effective_date=date(2026, 1, day),
        security_id=security,
        quantity=Decimal(quantity) if quantity else None,
        cost_basis=None,
    )


def test_incremental_replay_retains_fifo_unknown_basis_and_same_day_funding() -> None:
    """Daily advancement preserves source units, partial-sale basis and realized gains."""
    security: UUID = uuid4()
    unknown: UUID = uuid4()
    entries: list[LedgerEntry] = [
        entry(1, EntryKind.OPENING_CASH, "10"),
        entry(2, EntryKind.BUY, "200", security=security, quantity="2"),
        entry(3, EntryKind.DEPOSIT, "200"),
        entry(4, EntryKind.SELL, "150", day=5, security=security, quantity="1"),
        entry(5, EntryKind.OPENING_POSITION, "0", day=5, security=unknown, quantity="1"),
        entry(6, EntryKind.SELL, "200", day=6, security=unknown, quantity="1"),
    ]
    state: ReplayState = ReplayState()
    state.apply(entries[0], day_end=False)
    state.apply(entries[1], day_end=False)
    state.apply(entries[2], day_end=True)
    assert state.cash == Decimal("10")
    state.apply(entries[3], day_end=False)
    state.apply(entries[4], day_end=True)
    assert state.cash == Decimal("160")
    assert state.lots[security][0].basis == Decimal("100")
    assert state.realized == {4: Decimal("50")}
    state.apply(entries[5], day_end=True)
    assert state.cash == Decimal("360")
    assert state.realized == {4: Decimal("50"), 6: None}
    assert replay(entries) == (state.cash, state.lots, state.realized)
    assert entries[1].quantity == Decimal("2")
    assert entries[3].amount == Decimal("150")
