"""Recorded holdings priced independently of historical performance."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, DecimalException, localcontext
from uuid import UUID

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from sqlalchemy import Engine

from investor_platform.accounts import owned_account
from investor_platform.api_responses import decimal_json_response
from investor_platform.db import CurrentActor, DatabaseSession
from investor_platform.domain import (
    ACCOUNTING_PRECISION,
    MARKET_TIMEZONE,
    Currency,
    EntryKind,
    completed_market_date,
)
from investor_platform.ledger.schemas import HoldingView, LedgerView
from investor_platform.ledger.state import active_entries_for_account, ledger_view
from investor_platform.market_data import history as market_history
from investor_platform.market_data import listings as market_listings
from investor_platform.market_data import types as market_types
from investor_platform.market_data.types import History
from investor_platform.models import LedgerEntry
from investor_platform.performance.positions import position_episodes
from investor_platform.performance.statistics import trade_statistics
from investor_platform.performance.unrealized_return import annualized_unrealized_return

router = APIRouter(prefix="/api/accounts")
QUOTE_WINDOW = timedelta(days=10)
MAX_QUOTE_AGE = timedelta(days=4)


def current_position_starts(entries: list[LedgerEntry]) -> dict[UUID, date]:
    """Only the current flat-to-flat position can determine today's share units."""
    quantities, starts = {}, {}
    with localcontext() as ctx:
        ctx.prec = ACCOUNTING_PRECISION
        for entry in entries:
            if entry.security is None:
                continue
            sid = entry.security.id
            if not quantities.get(sid):
                starts[sid] = entry.effective_date
            quantity = entry.quantity * (-1 if entry.kind == EntryKind.SELL else 1)
            quantities[sid] = quantities.get(sid, Decimal(0)) + quantity
            if not quantities[sid]:
                starts.pop(sid)
    return starts


def latest(history: History, end: date) -> tuple[date, Decimal]:
    """Select a recent completed close on or before the requested cutoff."""
    day = max(d for d in history.close if d <= end)
    if end - day > MAX_QUOTE_AGE:
        raise ValueError("Latest close is stale")
    return day, history.close[day]


def quote_holding(
    holding: HoldingView,
    end: date,
    provisional: bool,
    fx: dict[str, History | str],
    engine: Engine | None = None,
    workspace_id: UUID | None = None,
    refresh_after: datetime | None = None,
    *,
    held_since: date,
) -> dict[str, UUID | str | date | Decimal | None]:
    """Price one holding while retaining an explicit missing-data reason."""
    security = holding.security
    start = min(held_since, end - QUOTE_WINDOW)
    row = {
        "security_id": security.id,
        "ticker": security.ticker,
        "exchange": security.exchange,
        "quantity": holding.quantity,
        "basis": holding.cost_basis,
        "close": None,
        "value": None,
        "weight": None,
        "unrealized_pnl": None,
        "quote_date": None,
        "price_error": None,
        "prices_fetched_at": None,
        "source": None,
    }
    try:
        history = market_history.listing_history(
            security,
            start,
            end,
            provisional=provisional,
            engine=engine,
            workspace_id=workspace_id,
            refresh_after=refresh_after,
        )
        day, price = latest(history, end)
        sources: list[History] = [history]
        foreign = market_listings.FOREIGN_LISTINGS.get(security.exchange)
        if foreign:
            currency = foreign[1]
            rate = fx[currency]
            if isinstance(rate, str):
                raise ValueError(rate)
            sources.append(rate)
            # Use same-date closing FX; never apply today's FX to a stale local quote.
            if day not in rate.close:
                raise ValueError("No matching USD exchange rate")
            with localcontext() as ctx:
                ctx.prec = ACCOUNTING_PRECISION
                price *= rate.close[day]
        split = next(
            (
                split
                for split in sorted(history.splits)
                if held_since < split <= end or day < split <= held_since
            ),
            None,
        )
        if split is not None:
            row["price_error"] = f"Split adjustment required ({split})"
            return row
        with localcontext() as ctx:
            ctx.prec = ACCOUNTING_PRECISION
            value = holding.quantity * price
            row.update(
                close=price,
                value=value,
                quote_date=day,
                unrealized_pnl=None if holding.cost_basis is None else value - holding.cost_basis,
                prices_fetched_at=market_types.collected_at(sources),
                source=" + ".join(sorted({source.source for source in sources})),
            )
    except (ValueError, OSError, KeyError, TypeError, IndexError, DecimalException):
        row["price_error"] = "Close unavailable: check listing, currency or market data"
    return row


def value_records(
    records: LedgerView,
    base_currency: Currency,
    provisional: bool,
    *,
    engine: Engine | None = None,
    workspace_id: UUID | None = None,
    refresh_after: datetime | None = None,
    end: date | None = None,
) -> dict:
    """Value supplied holdings at a selected date, defaulting to the latest close."""
    end = end or completed_market_date()
    starts = current_position_starts(records.entries)
    fx = {}
    for currency in {
        market_listings.FOREIGN_LISTINGS[h.security.exchange][1]
        for h in records.holdings
        if h.security.exchange in market_listings.FOREIGN_LISTINGS
    }:
        try:
            fx[currency] = market_history.fx_history(
                currency,
                end - QUOTE_WINDOW,
                end,
                engine=engine,
                workspace_id=workspace_id,
                refresh_after=refresh_after,
            )
        except (ValueError, OSError, KeyError, TypeError, IndexError, DecimalException):
            fx[currency] = "USD exchange rate unavailable"
    if base_currency == Currency.USD:
        with ThreadPoolExecutor(max_workers=6) as pool:
            rows = list(
                pool.map(
                    lambda h: quote_holding(
                        h,
                        end,
                        provisional,
                        fx,
                        engine,
                        workspace_id,
                        refresh_after,
                        held_since=starts[h.security.id],
                    ),
                    records.holdings,
                )
            )
    else:
        rows = [
            {
                "security_id": h.security.id,
                "ticker": h.security.ticker,
                "exchange": h.security.exchange,
                "quantity": h.quantity,
                "basis": h.cost_basis,
                "close": None,
                "value": None,
                "weight": None,
                "unrealized_pnl": None,
                "quote_date": None,
                "price_error": "Current quotes require a USD account",
                "prices_fetched_at": None,
                "source": None,
            }
            for h in records.holdings
        ]
    complete = all(row["value"] is not None for row in rows)
    with localcontext() as ctx:
        ctx.prec = ACCOUNTING_PRECISION
        value = (
            records.balance + sum((row["value"] for row in rows), Decimal(0)) if complete else None
        )
        if value and value > 0:
            for row in rows:
                row["weight"] = row["value"] / value
    return {
        "holdings": rows,
        "value": value,
        "cash": records.balance,
        "end": end,
        "provisional": provisional,
        "complete": complete,
        "source": " + ".join(
            sorted(
                {source for row in rows for source in (row["source"] or "").split(" + ") if source}
            )
        ),
        "fetched_at": datetime.now(UTC),
        "prices_fetched_at": (
            min(row["prices_fetched_at"] for row in rows)
            if rows and all(row["prices_fetched_at"] is not None for row in rows)
            else None
        ),
    }


@router.get("/{account_id}/valuation")
def valuation(account_id: UUID, session: DatabaseSession, actor: CurrentActor) -> Response:
    """Serve current recorded holdings independently of a return period."""
    account = owned_account(session, actor, account_id)
    records = ledger_view(active_entries_for_account(session, account_id), account.base_currency)
    result = value_records(
        records,
        account.base_currency,
        bool(account.reconstruction),
        engine=session.get_bind(),
        workspace_id=actor.workspace_id,
    )
    holdings = {holding.security.id: holding for holding in records.holdings}
    for row in result["holdings"]:
        rate, reason = (
            annualized_unrealized_return(
                holdings[row["security_id"]].lots, row["value"], row["quote_date"]
            )
            if row["value"] is not None and row["quote_date"] is not None
            else (None, "Market value unavailable")
        )
        row["annualized_unrealized_return"] = rate
        row["annualized_unrealized_return_reason"] = reason
    return decimal_json_response(result)


@router.get("/{account_id}/statistics/hypothetical")
def hypothetical_statistics(
    account_id: UUID, session: DatabaseSession, actor: CurrentActor
) -> Response:
    """Simulate closing positions without writing transactions."""
    account = owned_account(session, actor, account_id)
    entries = active_entries_for_account(session, account_id)
    today = datetime.now(MARKET_TIMEZONE).date()
    if entries and entries[-1].effective_date > today:
        raise HTTPException(422, "Wait until all recorded trade dates have arrived in New York")
    records = ledger_view(entries, account.base_currency)
    report = value_records(
        records,
        account.base_currency,
        bool(account.reconstruction),
        engine=session.get_bind(),
        workspace_id=actor.workspace_id,
    )
    details = [
        f"{r['ticker']}: {r['price_error']}" for r in report["holdings"] if r["value"] is None
    ]
    if details:
        raise HTTPException(503, "Latest prices unavailable for: " + "; ".join(details))
    securities = {e.security_id: e.security for e in entries if e.security_id}
    next_id = max((e.id for e in entries), default=0) + 1
    # Detached objects are only replayed in memory, never added to the session.
    sales = [
        LedgerEntry(
            id=next_id + index,
            kind=EntryKind.SELL,
            effective_date=today,
            security_id=row["security_id"],
            security=securities[row["security_id"]],
            quantity=row["quantity"],
            amount=row["value"],
        )
        for index, row in enumerate(report["holdings"])
    ]
    with localcontext() as ctx:
        ctx.prec = ACCOUNTING_PRECISION
        combined = [*entries, *sales]
        result = trade_statistics(combined)
        for row, episode in zip(result["episodes"], position_episodes(combined)[0], strict=True):
            row["hypothetical"] = episode[-1].id >= next_id
    dates = [r["quote_date"] for r in report["holdings"]]
    return decimal_json_response(
        {
            **result,
            "simulated_positions": len(sales),
            "quote_start": min(dates) if dates else None,
            "quote_end": max(dates) if dates else None,
            "source": report["source"],
            "fetched_at": report["fetched_at"],
        }
    )
