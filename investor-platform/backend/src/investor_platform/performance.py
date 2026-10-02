"""Daily closing-flow returns and fully closed position statistics."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, DecimalException, localcontext
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from . import market
from .accounting import replay
from .accounts import DB, Identity, owned_account
from .ledger import entries_for

router = APIRouter(prefix="/api/accounts")
ZERO = Decimal(0)
ONE = Decimal(1)


def wire(value):
    return JSONResponse(jsonable_encoder(value, custom_encoder={Decimal: lambda d: format(d, "f")}))


def position_episodes(entries):
    """Group each security from flat to flat, retaining buys and partial exits."""
    active, quantities, closed = {}, {}, []
    for entry in entries:
        sid = entry.security_id
        if sid is None:
            continue
        active.setdefault(sid, []).append(entry)
        quantities[sid] = quantities.get(sid, ZERO) + entry.quantity * (
            -1 if entry.kind == "sell" else 1
        )
        if quantities[sid] == 0:
            closed.append(active.pop(sid))
    return closed, len(active)


def trade_statistics(entries):
    _, _, realized = replay(entries)
    episodes, open_count = position_episodes(entries)
    closed = []
    for episode in episodes:
        last = episode[-1]
        gains = [realized[e.id] for e in episode if e.kind == "sell"]
        closed.append(
            {
                "ticker": last.security.ticker,
                "exchange": last.security.exchange,
                "closed_on": last.effective_date,
                "pnl": None if None in gains else sum(gains, ZERO),
            }
        )
    known = [e["pnl"] for e in closed if e["pnl"] is not None]
    wins = [p for p in known if p > 0]
    losses = [-p for p in known if p < 0]
    avg_win = sum(wins, ZERO) / len(wins) if wins else None
    avg_loss = sum(losses, ZERO) / len(losses) if losses else None
    return {
        "closed": len(closed),
        "open": open_count,
        "unknown": len(closed) - len(known),
        "wins": len(wins),
        "losses": len(losses),
        "breakeven": known.count(ZERO),
        "win_rate": Decimal(len(wins)) / len(known) if known else None,
        "average_win": avg_win,
        "average_loss": avg_loss,
        "payoff_ratio": avg_win / avg_loss if avg_win is not None and avg_loss else None,
        "realized_pnl": sum(known, ZERO) if known else None,
        "episodes": closed,
    }


@router.get("/{account_id}/statistics")
def statistics(account_id: UUID, session: DB, actor: Identity):
    owned_account(session, actor, account_id)
    with localcontext() as ctx:
        ctx.prec = 64
        return wire(trade_statistics(entries_for(session, account_id)))


class Period(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start: date
    end: date


def quote_symbol(security, provisional=False):
    if (
        provisional
        and security.currency == "USD"
        and (security.exchange in market.EXCHANGES or security.exchange == "UNVERIFIED")
    ):
        return security.ticker.replace(".", "-")
    return market.symbol_for(security)


def calculate(entries, histories, start, end, *, provisional=False):
    """No forward filling, shortened comparison window, or zero-valued missing positions."""
    spy, qqq = histories["SPY"], histories["QQQ"]
    days = sorted(d for d in spy.close if start <= d <= end)
    if len(days) < 2 or any(d not in qqq.adjusted for d in days):
        raise ValueError("Need at least two matching SPY and QQQ closing sessions")
    if (end - days[-1]).days > 4:
        raise ValueError("Benchmark history is stale at the requested end date")
    securities = {e.security_id: e.security for e in entries if e.security_id}
    prices = {sid: histories[quote_symbol(s, provisional)] for sid, s in securities.items()}
    for sid, security in securities.items():
        if provisional:
            if prices[sid].exchange not in set().union(*market.EXCHANGES.values()):
                raise ValueError(
                    f"{security.ticker}: provider listing is not a supported US listing"
                )
        else:
            market.verify_exchange(security, prices[sid])
    # If shares span a split, the ledger needs a corporate-action record (not supported yet).
    for sid, h in prices.items():
        for d in sorted(h.splits):
            if d > days[-1]:
                continue
            quantity = sum(
                (
                    e.quantity * (-1 if e.kind == "sell" else 1)
                    for e in entries
                    if e.security_id == sid and e.effective_date < d
                ),
                ZERO,
            )
            if quantity:
                raise ValueError(
                    f"{securities[sid].ticker}: shares span a split on {d}; "
                    "split accounting is not supported yet"
                )
    values = []
    growth = ONE
    previous = None
    previous_day = None
    warnings = []
    distributions = {}
    for sid, h in prices.items():
        for exdate, dividend in h.dividends.items():
            if exdate > days[-1]:
                continue
            shares = sum(
                (
                    e.quantity * (-1 if e.kind == "sell" else 1)
                    for e in entries
                    if e.security_id == sid and e.effective_date < exdate
                ),
                ZERO,
            )
            distributions[exdate] = distributions.get(exdate, ZERO) + shares * dividend
    modeled_income = {}
    for exdate, expected in sorted(distributions.items()):
        income = sum(
            (e.amount for e in entries if e.kind == "income" and e.effective_date == exdate), ZERO
        )
        if provisional:
            # Fill only the missing gross amount on its ex-date; never write modeled income.
            modeled_income[exdate] = max(ZERO, expected - income)
        elif expected > 0 and abs(income - expected) > Decimal("0.01"):
            warnings.append(
                f"Income needs reconciliation for {exdate}: expected gross distributions "
                f"{expected:.2f}, recorded {income:.2f}. Record income on the ex-date."
            )
    latest_holdings = []
    for d in days:
        prefix = [e for e in entries if e.effective_date <= d]
        cash, lots, _ = replay(prefix)
        cash += sum((amount for day, amount in modeled_income.items() if day <= d), ZERO)
        holdings = []
        for sid, sl in lots.items():
            quantity = sum((lot.quantity for lot in sl), ZERO)
            if not quantity:
                continue
            price = prices[sid].close.get(d)
            if price is None:
                raise ValueError(
                    f"Missing close for {securities[sid].ticker} on {d}; no partial valuation shown"
                )
            basis = (
                None
                if any(lot.quantity and lot.basis is None for lot in sl)
                else sum((lot.basis or ZERO for lot in sl), ZERO)
            )
            holdings.append(
                {
                    "ticker": securities[sid].ticker,
                    "exchange": securities[sid].exchange,
                    "quantity": quantity,
                    "close": price,
                    "value": quantity * price,
                    "basis": basis,
                    "unrealized_pnl": None if basis is None else quantity * price - basis,
                }
            )
        value = cash + sum((h["value"] for h in holdings), ZERO)
        if previous is not None:
            interval = [e for e in entries if previous_day < e.effective_date <= d]
            flow = ZERO
            for e in interval:
                if e.kind in {"deposit", "opening_cash"}:
                    flow += e.amount
                elif e.kind == "withdrawal":
                    flow -= e.amount
                elif e.kind == "opening_position":
                    price = prices[e.security_id].close.get(d)
                    if price is None:
                        raise ValueError("Missing price for an in-kind contribution")
                    flow += e.quantity * price
            if previous <= 0:
                raise ValueError(
                    "Return is undefined across a zero-value balance; "
                    "select a continuously funded period"
                )
            factor = (value - flow) / previous
            if factor < 0:
                raise ValueError(
                    "Closing-flow convention is invalid for this cash movement; "
                    "intraday valuations are needed"
                )
            growth *= factor
        for h in holdings:
            h["weight"] = h["value"] / value if value else None
        values.append(
            {
                "date": d,
                "value": value,
                "cash": cash,
                "portfolio": growth - ONE,
                "SPY": spy.adjusted[d] / spy.adjusted[days[0]] - ONE,
                "QQQ": qqq.adjusted[d] / qqq.adjusted[days[0]] - ONE,
            }
        )
        previous, previous_day, latest_holdings = value, d, holdings
    if warnings:
        for row in values:
            row["portfolio"] = None
    last = values[-1]
    return {
        "provisional": provisional,
        "modeled_income": sum(modeled_income.values(), ZERO),
        "assumptions": [
            "Testing estimate: opening shares and cash are inferred, not verified broker balances.",
            "Assumes no missing trades or external flows; excluded import rows are not included.",
            "Uses provider USD listings for imported US tickers; confirm security identity.",
            "Missing gross distributions are modeled on ex-dates and held as cash. Recorded income "
            "offsets the model only on the same ex-date; payment-date income may double count it.",
            "No unrecorded fees or taxes. Benchmarks reinvest distributions.",
        ]
        if provisional
        else [],
        "start": days[0],
        "end": days[-1],
        "value": last["value"],
        "cash": last["cash"],
        "holdings": latest_holdings,
        "series": values,
        "warnings": warnings,
        "return": last["portfolio"],
        "SPY": last["SPY"],
        "QQQ": last["QQQ"],
        "excess_spy": None if warnings else last["portfolio"] - last["SPY"],
        "excess_qqq": None if warnings else last["portfolio"] - last["QQQ"],
    }


@router.post("/{account_id}/performance")
def performance(account_id: UUID, period: Period, session: DB, actor: Identity):
    account = owned_account(session, actor, account_id)
    provisional = bool(account.reconstruction)
    entries = entries_for(session, account_id)
    if account.base_currency != "USD":
        raise HTTPException(
            422,
            "Market comparisons currently require a USD account; FX conversion is not supported",
        )
    today = datetime.now(ZoneInfo("America/New_York")).date()
    if (
        period.start >= period.end
        or period.end >= today
        or period.start < today - timedelta(days=3660)
    ):
        raise HTTPException(
            422,
            "Choose a period of at least two days within the past ten years, "
            "ending before today (New York)",
        )
    if not entries or period.start < entries[0].effective_date:
        raise HTTPException(422, "Start on or after your first ledger entry")
    entries = [e for e in entries if e.effective_date <= period.end]
    securities = {e.security_id: e.security for e in entries if e.security_id}
    try:
        symbols = {quote_symbol(s, provisional) for s in securities.values()} | {"SPY", "QQQ"}
        if len(securities) > 48 or entries[0].effective_date < today - timedelta(days=3660):
            raise ValueError(
                "This first tracker supports up to 48 securities and ten years of ledger history"
            )
        # Fetch from inception to detect unrecorded historical splits, even for a recent report.
        fetched = market.histories(symbols, entries[0].effective_date, period.end)
        with localcontext() as ctx:
            ctx.prec = 64
            result = calculate(entries, fetched, period.start, period.end, provisional=provisional)
        return wire(
            {**result, "fetched_at": datetime.now(UTC), "source": "Yahoo Finance daily history"}
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except (OSError, KeyError, TypeError, IndexError, DecimalException) as exc:
        raise HTTPException(
            503,
            "Market data is unavailable or incomplete. "
            "Your ledger is unchanged; retry the comparison.",
        ) from exc
