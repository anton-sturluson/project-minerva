"""Daily closing-flow returns and fully closed position statistics."""

from datetime import UTC, date, datetime
from decimal import Decimal, DecimalException, localcontext
from enum import StrEnum
from uuid import UUID

from fastapi import APIRouter, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from . import market
from .accounting import replay
from .accounts import DB, Identity, owned_account
from .domain import ACCOUNTING_PRECISION, Currency, EntryKind
from .ledger import entries_for
from .models import LedgerEntry

router = APIRouter(prefix="/api/accounts")
ZERO = Decimal(0)
ONE = Decimal(1)
DAYS_PER_YEAR = Decimal("365.25")


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
            -1 if entry.kind == EntryKind.SELL else 1
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
        gains = [realized[e.id] for e in episode if e.kind == EntryKind.SELL]
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
        ctx.prec = ACCOUNTING_PRECISION
        return wire(trade_statistics(entries_for(session, account_id)))


class Baseline(StrEnum):
    HISTORY = "history"
    RECORDED = "recorded"


class Period(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start: date
    end: date
    baseline: Baseline = Baseline.HISTORY
    exclude_security_ids: list[UUID] = Field(default_factory=list, max_length=market.MAX_SECURITIES)


def period_securities(entries, start=None):
    """Keep every ledger lot; only skip price history for positions already closed."""
    securities = {e.security_id: e.security for e in entries if e.security_id}
    if start is None:
        return securities
    _, lots, _ = replay([e for e in entries if e.effective_date < start])
    needed = {sid for sid, position in lots.items() if any(lot.quantity for lot in position)}
    needed.update(e.security_id for e in entries if e.effective_date >= start and e.security_id)
    return {sid: security for sid, security in securities.items() if sid in needed}


def annualized_return(cumulative, start, end):
    """Annualize the linked return, never the raw balance change."""
    days = (end - start).days
    if cumulative is None or days < 365:
        return None
    if cumulative == -ONE:
        return -ONE
    return (ONE + cumulative) ** (DAYS_PER_YEAR / Decimal(days)) - ONE


def scenario_entries(entries, excluded, histories, *, provisional, start=None):
    """Build a read-only cash alternative; never mutate or attach ledger objects."""
    prefix = [] if start is None else [e for e in entries if e.effective_date < start]
    current = entries if start is None else [e for e in entries if e.effective_date >= start]
    if any(e.kind == EntryKind.INCOME for e in current):
        raise ValueError(
            "Scenario unavailable: recorded income is not linked to individual stocks yet"
        )
    result = list(prefix)
    sessions = sorted(histories["SPY"].close)
    if prefix:
        _, lots, _ = replay(prefix)
        securities = {e.security_id: e.security for e in prefix if e.security_id}
        day = next((d for d in sessions if d >= start), None)
        for index, sid in enumerate(sorted(excluded)):
            quantity = sum((lot.quantity for lot in lots.get(sid, [])), ZERO)
            if not quantity:
                continue
            symbol = market.symbol_for(securities[sid], provisional=provisional)
            price = histories[symbol].close.get(day)
            if price is None:
                raise ValueError("Scenario unavailable: missing opening-position valuation")
            # Release opening capital at the first session close; preserve all earlier trades.
            result.append(
                LedgerEntry(
                    id=-index - 1,
                    kind=EntryKind.SELL,
                    effective_date=start,
                    security_id=sid,
                    security=securities[sid],
                    quantity=quantity,
                    amount=quantity * price,
                )
            )
    for entry in current:
        if entry.security_id not in excluded:
            result.append(entry)
        elif entry.kind == EntryKind.OPENING_POSITION:
            # Preserve contributed capital: replace opening shares with their first session value.
            day = next((d for d in sessions if d >= entry.effective_date), None)
            symbol = market.symbol_for(entry.security, provisional=provisional)
            price = histories[symbol].close.get(day)
            if price is None:
                raise ValueError("Scenario unavailable: missing opening-position valuation")
            result.append(
                LedgerEntry(
                    id=entry.id,
                    kind=EntryKind.DEPOSIT,
                    effective_date=entry.effective_date,
                    amount=entry.quantity * price,
                    security_id=None,
                )
            )
        # Excluded buys, sales and their fees disappear together. Other cash flows stay intact.
    try:
        replay(result)
    except HTTPException as exc:
        raise ValueError(
            "Scenario unavailable: remaining trades or withdrawals need cash from excluded stocks"
        ) from exc
    return result


def calculate(entries, histories, start, end, *, provisional=False, baseline=Baseline.HISTORY):
    """Link USD valuations on benchmark sessions; never zero-value missing positions."""
    spy, qqq = histories["SPY"], histories["QQQ"]
    days = sorted(d for d in spy.close if start <= d <= end)
    if len(days) < 2 or any(d not in qqq.adjusted for d in days):
        raise ValueError("Need at least two matching SPY and QQQ closing sessions")
    if (end - days[-1]).days > 4:
        raise ValueError("Benchmark history is stale at the requested end date")
    securities = period_securities(entries, start if baseline == Baseline.RECORDED else None)
    prices = {
        sid: histories[market.symbol_for(s, provisional=provisional)]
        for sid, s in securities.items()
    }
    for sid, security in securities.items():
        market.verify_exchange(security, prices[sid], provisional=provisional)
    # If shares span a split, the ledger needs a corporate-action record (not supported yet).
    for sid, h in prices.items():
        for d in sorted(h.splits):
            if d > days[-1] or (baseline == Baseline.RECORDED and d < start):
                continue
            quantity = sum(
                (
                    e.quantity * (-1 if e.kind == EntryKind.SELL else 1)
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
            if exdate > days[-1] or (baseline == Baseline.RECORDED and exdate < start):
                continue
            shares = sum(
                (
                    e.quantity * (-1 if e.kind == EntryKind.SELL else 1)
                    for e in entries
                    if e.security_id == sid and e.effective_date < exdate
                ),
                ZERO,
            )
            distributions[exdate] = distributions.get(exdate, ZERO) + shares * dividend
    modeled_income = {}
    for exdate, expected in sorted(distributions.items()):
        income = sum(
            (
                e.amount
                for e in entries
                if e.kind == EntryKind.INCOME and e.effective_date == exdate
            ),
            ZERO,
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
                if e.kind in {EntryKind.DEPOSIT, EntryKind.OPENING_CASH}:
                    flow += e.amount
                elif e.kind == EntryKind.WITHDRAWAL:
                    flow -= e.amount
                elif e.kind == EntryKind.OPENING_POSITION:
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
            "Uses exchange-specific listings and dated USD FX; confirm security identity.",
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
        "cagr": {
            key: annualized_return(last[key], days[0], days[-1])
            for key in ("portfolio", *market.BENCHMARKS)
        },
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
    if account.base_currency != Currency.USD:
        raise HTTPException(
            422,
            "Market comparisons currently require a USD account; FX conversion is not supported",
        )
    today = datetime.now(market.MARKET_TIMEZONE).date()
    if (
        period.start >= period.end
        or period.end >= today
        or period.start < today - market.HISTORY_WINDOW
    ):
        raise HTTPException(
            422,
            "Choose a period of at least two days within the past ten years, "
            "ending before today (New York)",
        )
    if not entries or period.start < entries[0].effective_date:
        raise HTTPException(422, "Start on or after your first ledger entry")
    entries = [e for e in entries if e.effective_date <= period.end]
    recorded = period.baseline == Baseline.RECORDED
    securities = period_securities(entries, period.start if recorded else None)
    fetch_start = period.start if recorded else entries[0].effective_date
    excluded = set(period.exclude_security_ids)
    if not excluded.issubset(securities):
        raise HTTPException(422, "Choose excluded stocks held during this comparison period")
    try:
        if len(securities) > market.MAX_SECURITIES or fetch_start < today - market.HISTORY_WINDOW:
            raise ValueError(
                f"This tracker supports up to {market.MAX_SECURITIES} securities "
                "and ten years of ledger history"
            )
        # Full-history mode validates from inception; recorded mode trusts opening share units.
        fetched = market.security_histories(
            securities.values(), fetch_start, period.end, provisional=provisional
        )
        with localcontext() as ctx:
            ctx.prec = ACCOUNTING_PRECISION
            result = calculate(
                entries,
                fetched,
                period.start,
                period.end,
                provisional=provisional,
                baseline=period.baseline,
            )
            result["baseline"] = period.baseline
            result["security_ids"] = list(securities)
            result["scenario"] = None
            result["scenario_error"] = None
            if excluded:
                try:
                    alternative = scenario_entries(
                        entries,
                        excluded,
                        fetched,
                        provisional=provisional,
                        start=period.start if recorded else None,
                    )
                    result["scenario"] = calculate(
                        alternative,
                        fetched,
                        period.start,
                        period.end,
                        provisional=provisional,
                        baseline=period.baseline,
                    )
                    result["scenario"]["excluded"] = [
                        {"id": sid, "ticker": s.ticker, "exchange": s.exchange}
                        for sid, s in securities.items()
                        if sid in excluded
                    ]
                except ValueError as exc:
                    result["scenario_error"] = str(exc)
        return wire({**result, "fetched_at": datetime.now(UTC), "source": market.SOURCE})
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except market.MarketDataError as exc:
        raise HTTPException(503, str(exc)) from exc
    except (OSError, KeyError, TypeError, IndexError, DecimalException) as exc:
        raise HTTPException(
            503,
            "Market data is unavailable or incomplete. "
            "Your ledger is unchanged; retry the comparison.",
        ) from exc
