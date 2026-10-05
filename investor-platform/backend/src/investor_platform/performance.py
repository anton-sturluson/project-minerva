"""Daily cash-flow-adjusted returns and fully closed position statistics."""

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
from .attribution import StockAttribution
from .domain import (
    ACCOUNTING_PRECISION,
    IN_KIND_ENTRIES,
    MARKET_TIMEZONE,
    Currency,
    EntryKind,
    FundingStatus,
    IncomeKind,
    completed_market_date,
)
from .income import dividend_receivables, market_dividends
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


class PerformanceScope(StrEnum):
    ACCOUNT = "account"
    STOCKS = "stocks"


class Period(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start: date
    end: date
    anchor_date: date | None = None
    scope: PerformanceScope = PerformanceScope.ACCOUNT
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


def holding_windows(entries, securities, start, end, *, provisional):
    """Daily valuation only needs prices while a position is held, never after its final sale."""
    windows = {}
    for sid, security in securities.items():
        rows = [e for e in entries if e.security_id == sid]
        quantity = sum((e.quantity * (-1 if e.kind == EntryKind.SELL else 1) for e in rows), ZERO)
        first = max(start, rows[0].effective_date)
        last = end if quantity else min(end, rows[-1].effective_date)
        windows[market.symbol_for(security, provisional=provisional)] = (first, last)
    return windows


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
    if any(
        e.kind == EntryKind.INCOME
        and (
            e.income_kind is None
            or (e.income_kind == IncomeKind.OTHER and e.income_security_id is None)
        )
        for e in current
    ):
        raise ValueError(
            "Scenario unavailable: classify income and link stock-specific payments "
            "to their security"
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
        if entry.income_security_id in excluded and (
            entry.income_kind != IncomeKind.DIVIDEND or start is None or entry.accrual_date > start
        ):
            continue
        if entry.security_id not in excluded:
            result.append(entry)
        elif entry.kind in IN_KIND_ENTRIES:
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


def funded_stock_entries(entries):
    """Read-only stock sleeve: each purchase is funded and each sale removes proceeds.

    These balancing flows exist only for calculation, never in the stored ledger.
    They preserve execution amounts (including recorded fees) and FIFO ordering.
    """
    result = []
    for entry in entries:
        if entry.security_id is None:
            continue
        result.append(entry)
        if entry.kind in {EntryKind.BUY, EntryKind.SELL}:
            result.append(
                LedgerEntry(
                    kind=EntryKind.DEPOSIT if entry.kind == EntryKind.BUY else EntryKind.WITHDRAWAL,
                    effective_date=entry.effective_date,
                    amount=entry.amount,
                )
            )
    return result


def calculate(
    entries,
    histories,
    start,
    end,
    *,
    provisional=False,
    baseline=Baseline.HISTORY,
    funding_status=FundingStatus.RECORDED,
    closing_cash_ids=frozenset(),
    scope=PerformanceScope.ACCOUNT,
):
    """Link USD valuations on benchmark sessions; never zero-value missing positions."""
    stock_only = scope == PerformanceScope.STOCKS
    if stock_only:
        entries = funded_stock_entries(entries)
        if not entries:
            raise ValueError("Choose at least one stock with recorded holdings or trades")
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
    if not stock_only and funding_status == FundingStatus.INFERRED:
        warnings.append("Cash history needs reconciliation; starting funding was inferred.")
    distributions = {}
    if stock_only:
        # Estimated gross distributions are paid out of this stock sleeve on the ex-date.
        # Actual broker cash, payment timing, interest and currency cash are outside its scope.
        distributions = market_dividends(entries, prices, days[-1])
        receivables = dict.fromkeys(days, ZERO)
    else:
        receivables, income_warnings = dividend_receivables(
            entries,
            prices,
            securities,
            days,
            validation_start=start if baseline == Baseline.RECORDED else None,
        )
        warnings.extend(income_warnings)
    latest_holdings = []
    attribution = StockAttribution(securities) if stock_only else None
    for d in days:
        prefix = [e for e in entries if e.effective_date <= d]
        cash, lots, _ = replay(prefix)
        holdings = []
        holding_values = {}
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
            holding_values[sid] = quantity * price
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
        value = cash + receivables[d] + sum((h["value"] for h in holdings), ZERO)
        growth_before = growth
        interval = []
        denominator = ZERO
        if previous is not None:
            interval = [e for e in entries if previous_day < e.effective_date <= d]
            incoming = outgoing = in_kind = ZERO
            for e in interval:
                if e.kind in {EntryKind.DEPOSIT, EntryKind.OPENING_CASH}:
                    if e.id in closing_cash_ids:
                        in_kind += e.amount
                    else:
                        incoming += e.amount
                elif e.kind == EntryKind.WITHDRAWAL:
                    outgoing += e.amount
                elif e.kind in IN_KIND_ENTRIES:
                    price = prices[e.security_id].close.get(d)
                    if price is None:
                        raise ValueError("Missing price for an in-kind contribution")
                    in_kind += e.quantity * price
            if previous <= 0 and not stock_only:
                raise ValueError(
                    "Return is undefined across a zero-value balance; "
                    "select a continuously funded period"
                )
            # Dated cash deposits are available to invest at the start of the session.
            # Withdrawals and close-valued in-kind receipts occur at its end.
            dividend = sum(
                (
                    amount
                    for (_, exdate), amount in distributions.items()
                    if previous_day < exdate <= d
                ),
                ZERO,
            )
            denominator = previous + incoming
            # Flat periods have no invested capital. A new in-kind position starts at its close.
            factor = (value + outgoing + dividend - in_kind) / denominator if denominator else ONE
            if factor < 0:
                raise ValueError(
                    "Daily flow convention is invalid for this cash movement; "
                    "intraday valuations are needed"
                )
            growth *= factor
        if attribution is not None:
            attribution.record(
                d,
                previous_day,
                holding_values,
                interval,
                prices,
                distributions,
                denominator,
                growth_before,
                growth,
            )
        for h in holdings:
            h["weight"] = h["value"] / value if value else None
        values.append(
            {
                "date": d,
                "value": value,
                "cash": cash,
                "receivables": receivables[d],
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
        "attribution": attribution.report() if attribution is not None else None,
        "scope": scope,
        "provisional": provisional or stock_only,
        "funding_status": funding_status,
        "receivables": receivables[days[-1]],
        "assumptions": [
            "Stock sleeve only: idle cash, cash FX, interest and account-level expenses excluded.",
            "Purchases fund the sleeve at session start; sale proceeds leave at session end.",
            "Provider-estimated gross dividends leave the sleeve on the ex-date; "
            "no broker cash is invented.",
            "Recorded execution amounts include only recorded trading costs. "
            "Benchmarks reinvest distributions.",
        ]
        if stock_only
        else [
            "Testing estimate: opening shares and cash are inferred, not verified broker balances.",
            "Assumes no missing trades or external flows; excluded import rows are not included.",
            "Uses exchange-specific listings and dated USD FX; confirm security identity.",
            "Dividends accrue on their recorded ex-dates and become cash on payment dates. "
            "Missing or mismatched distributions withhold returns; "
            "interest is recognized when posted.",
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
    funding_status = FundingStatus.RECORDED
    if provisional:
        funding_status = FundingStatus(
            account.reconstruction.get("funding_status", FundingStatus.INFERRED)
        )
    entries = entries_for(session, account_id)
    if account.base_currency != Currency.USD:
        raise HTTPException(
            422,
            "Market comparisons currently require a USD account; FX conversion is not supported",
        )
    today = datetime.now(MARKET_TIMEZONE).date()
    if (
        period.start >= period.end
        or period.end > completed_market_date()
        or period.start < today - market.HISTORY_WINDOW
    ):
        raise HTTPException(
            422,
            "Choose a period of at least two days within the past ten years, "
            "ending by the latest available date (today after 5 p.m. New York)",
        )
    if not entries or period.start < entries[0].effective_date:
        raise HTTPException(422, "Start on or after your first ledger entry")
    entries = [
        e
        for e in entries
        if e.effective_date <= period.end
        or (e.income_kind == IncomeKind.DIVIDEND and e.accrual_date <= period.end)
    ]
    if period.anchor_date is not None and period.anchor_date >= period.end:
        raise HTTPException(422, "The comparison boundary must precede the ending date")
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
            securities.values(),
            fetch_start,
            period.end,
            provisional=provisional,
            engine=session.get_bind(),
            workspace_id=actor.workspace_id,
            windows=holding_windows(
                entries, securities, fetch_start, period.end, provisional=provisional
            ),
        )
        calculation_start = period.start
        if period.anchor_date is not None:
            sessions = sorted(d for d in fetched["SPY"].close if period.start <= d <= period.end)
            before = [d for d in sessions if d <= period.anchor_date]
            if sessions:
                calculation_start = before[-1] if before else sessions[0]
        with localcontext() as ctx:
            ctx.prec = ACCOUNTING_PRECISION
            result = calculate(
                entries,
                fetched,
                calculation_start,
                period.end,
                provisional=provisional,
                baseline=period.baseline,
                funding_status=funding_status,
                scope=period.scope,
            )
            result["baseline"] = period.baseline
            result["security_ids"] = list(securities)
            result["scenario"] = None
            result["scenario_error"] = None
            if (
                excluded
                and period.scope == PerformanceScope.ACCOUNT
                and funding_status == FundingStatus.INFERRED
            ):
                result["scenario_error"] = "Reconcile cash history before comparing exclusions"
            elif excluded:
                try:
                    alternative = (
                        [e for e in entries if e.security_id not in excluded]
                        if period.scope == PerformanceScope.STOCKS
                        else scenario_entries(
                            entries,
                            excluded,
                            fetched,
                            provisional=provisional,
                            start=calculation_start if recorded else None,
                        )
                    )
                    result["scenario"] = calculate(
                        alternative,
                        fetched,
                        calculation_start,
                        period.end,
                        provisional=provisional,
                        baseline=period.baseline,
                        funding_status=funding_status,
                        scope=period.scope,
                        closing_cash_ids={
                            e.id
                            for e in entries
                            if e.kind in IN_KIND_ENTRIES and e.security_id in excluded
                        },
                    )
                    result["scenario"]["excluded"] = [
                        {"id": sid, "ticker": s.ticker, "exchange": s.exchange}
                        for sid, s in securities.items()
                        if sid in excluded
                    ]
                except ValueError as exc:
                    result["scenario_error"] = str(exc)
        return wire(
            {
                **result,
                "fetched_at": datetime.now(UTC),
                "source": " + ".join(
                    sorted({source for h in fetched.values() for source in h.source.split(" + ")})
                ),
            }
        )
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
