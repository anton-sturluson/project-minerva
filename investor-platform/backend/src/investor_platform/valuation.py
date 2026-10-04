"""Current recorded holdings priced independently of historical performance."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal, DecimalException, localcontext
from uuid import UUID

from fastapi import APIRouter, HTTPException

from . import market
from .accounts import DB, Identity, owned_account
from .domain import ACCOUNTING_PRECISION, MARKET_TIMEZONE, Currency, EntryKind
from .ledger import entries_for, ledger_view
from .models import LedgerEntry
from .performance import position_episodes, trade_statistics, wire

router = APIRouter(prefix="/api/accounts")
QUOTE_WINDOW = timedelta(days=10)
MAX_QUOTE_AGE = timedelta(days=4)


def latest(history, end):
    day = max(d for d in history.close if d <= end)
    if end - day > MAX_QUOTE_AGE:
        raise ValueError("Latest close is stale")
    return day, history.close[day]


def quote_holding(holding, end, provisional, fx):
    security = holding.security
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
    }
    try:
        foreign = market.FOREIGN_LISTINGS.get(security.exchange)
        if foreign:
            suffix, currency, exchanges = foreign
            history = market.history(
                security.ticker + suffix, end - QUOTE_WINDOW, end, currency=currency
            )
            if history.exchange not in exchanges:
                raise ValueError("Provider listing does not match the recorded exchange")
            day, price = latest(history, end)
            rate = fx[currency]
            if isinstance(rate, str):
                raise ValueError(rate)
            # Use same-date closing FX; never apply today's FX to a stale local quote.
            if day not in rate.close:
                raise ValueError("No matching USD exchange rate")
            with localcontext() as ctx:
                ctx.prec = ACCOUNTING_PRECISION
                price *= rate.close[day]
        else:
            symbol = market.symbol_for(security, provisional=provisional)
            history = market.history(symbol, end - QUOTE_WINDOW, end)
            market.verify_exchange(security, history, provisional=provisional)
            day, price = latest(history, end)
        with localcontext() as ctx:
            ctx.prec = ACCOUNTING_PRECISION
            value = holding.quantity * price
            row.update(
                close=price,
                value=value,
                quote_date=day,
                unrealized_pnl=None if holding.cost_basis is None else value - holding.cost_basis,
            )
    except (ValueError, OSError, KeyError, TypeError, IndexError, DecimalException):
        row["price_error"] = "Close unavailable: check listing, currency or market data"
    return row


def value_records(records, base_currency, provisional):
    end = datetime.now(MARKET_TIMEZONE).date() - timedelta(days=1)
    fx = {}
    for currency in {
        market.FOREIGN_LISTINGS[h.security.exchange][1]
        for h in records.holdings
        if h.security.exchange in market.FOREIGN_LISTINGS
    }:
        try:
            fx[currency] = market.history(
                f"{currency}USD=X", end - QUOTE_WINDOW, end, instruments=("CURRENCY",)
            )
        except (ValueError, OSError, KeyError, TypeError, IndexError, DecimalException):
            fx[currency] = "USD exchange rate unavailable"
    if base_currency == Currency.USD:
        with ThreadPoolExecutor(max_workers=6) as pool:
            rows = list(
                pool.map(
                    lambda h: quote_holding(h, end, provisional, fx),
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
        "source": market.SOURCE,
        "fetched_at": datetime.now(UTC),
    }


@router.get("/{account_id}/valuation")
def valuation(account_id: UUID, session: DB, actor: Identity):
    account = owned_account(session, actor, account_id)
    records = ledger_view(entries_for(session, account_id), account.base_currency)
    return wire(value_records(records, account.base_currency, bool(account.reconstruction)))


@router.get("/{account_id}/statistics/hypothetical")
def hypothetical_statistics(account_id: UUID, session: DB, actor: Identity):
    account = owned_account(session, actor, account_id)
    entries = entries_for(session, account_id)
    today = datetime.now(MARKET_TIMEZONE).date()
    if entries and entries[-1].effective_date > today:
        raise HTTPException(422, "Wait until all recorded trade dates have arrived in New York")
    records = ledger_view(entries, account.base_currency)
    report = value_records(records, account.base_currency, bool(account.reconstruction))
    missing = [r["ticker"] for r in report["holdings"] if r["value"] is None]
    if missing:
        raise HTTPException(503, "Latest prices unavailable for: " + ", ".join(missing))
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
    return wire(
        {
            **result,
            "simulated_positions": len(sales),
            "quote_start": min(dates) if dates else None,
            "quote_end": max(dates) if dates else None,
            "source": report["source"],
            "fetched_at": report["fetched_at"],
        }
    )
