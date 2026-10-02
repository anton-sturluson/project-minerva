"""Closed investment decisions versus capital- and holding-period-matched benchmarks."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal, DecimalException, localcontext
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException

from . import market
from .accounting import UNIT
from .accounts import DB, Identity, owned_account
from .ledger import entries_for
from .performance import position_episodes, wire

router = APIRouter(prefix="/api/accounts")
BENCHMARKS = ("SPY", "QQQ")
ZERO = Decimal(0)
CENT = Decimal("0.01")


def exclusion(episode, today):
    if any(e.kind == "opening_position" for e in episode):
        return "Opening position: original purchase dates are unknown"
    if episode[-1].effective_date >= today:
        return "Wait for completed closing prices after today's trades"
    if episode[0].effective_date < today - timedelta(days=3660):
        return "Purchase history exceeds the ten-year data window"
    try:
        market.symbol_for(episode[0].security)
    except ValueError as exc:
        return str(exc)
    return None


def compare_episode(episode, histories):
    security = episode[0].security
    history = histories[market.symbol_for(security)]
    market.verify_exchange(security, history)
    start, end = episode[0].effective_date, episode[-1].effective_date
    for day in history.splits | history.dividends.keys():
        if start < day <= end:
            quantity = sum(
                (
                    e.quantity * (-1 if e.kind == "sell" else 1)
                    for e in episode
                    if e.effective_date < day
                ),
                ZERO,
            )
            if quantity:
                if day in history.splits:
                    raise ValueError("Position spans a split; split accounting is unavailable")
                raise ValueError(
                    "Position earned a distribution; stock-level income is not recorded"
                )
    # Require actual sessions on every trade date; no previous/next-day substitution.
    for entry in episode:
        if entry.effective_date not in history.close or any(
            entry.effective_date not in histories[b].adjusted for b in BENCHMARKS
        ):
            raise ValueError("Missing matching closing prices on a trade date")
    lots = []
    invested = sum((e.amount for e in episode if e.kind == "buy"), ZERO)
    pnl = sum((e.amount for e in episode if e.kind == "sell"), ZERO) - invested
    benchmark_pnl = dict.fromkeys(BENCHMARKS, ZERO)
    for entry in episode:
        if entry.kind == "buy":
            lots.append(
                {"quantity": entry.quantity, "cost": entry.amount, "date": entry.effective_date}
            )
            continue
        remaining = entry.quantity
        for lot in lots:
            take = min(remaining, lot["quantity"])
            if not take:
                continue
            cost = (
                lot["cost"]
                if take == lot["quantity"]
                else (lot["cost"] * take / lot["quantity"]).quantize(UNIT, ROUND_HALF_EVEN)
            )
            for benchmark in BENCHMARKS:
                adjusted = histories[benchmark].adjusted
                benchmark_pnl[benchmark] += cost * (
                    adjusted[entry.effective_date] / adjusted[lot["date"]] - 1
                )
            lot["cost"] -= cost
            lot["quantity"] -= take
            remaining -= take
    return {
        "pnl": pnl,
        "benchmarks": {
            b: {
                "pnl": benchmark_pnl[b],
                "excess": (pnl - benchmark_pnl[b]).quantize(CENT, ROUND_HALF_EVEN),
            }
            for b in BENCHMARKS
        },
    }


def calculate_hit_rate(episodes, open_count, histories, today):
    rows = []
    for episode in episodes:
        first, last = episode[0], episode[-1]
        row = {
            "ticker": first.security.ticker,
            "exchange": first.security.exchange,
            "opened_on": first.effective_date,
            "closed_on": last.effective_date,
            "excluded": exclusion(episode, today),
        }
        if not row["excluded"]:
            try:
                row.update(compare_episode(episode, histories))
            except ValueError as exc:
                row["excluded"] = str(exc)
        rows.append(row)
    eligible = [r for r in rows if not r["excluded"]]
    metrics = {}
    for benchmark in BENCHMARKS:
        excess = [r["benchmarks"][benchmark]["excess"] for r in eligible]
        hits = sum(x > ZERO for x in excess)
        metrics[benchmark] = {
            "hit_rate": Decimal(hits) / len(eligible) if eligible else None,
            "hits": hits,
            "evaluated": len(eligible),
            "ties": excess.count(ZERO),
        }
    return {
        "benchmarks": metrics,
        "episodes": rows,
        "open": open_count,
        "excluded": len(rows) - len(eligible),
    }


@router.post("/{account_id}/hit-rate")
def hit_rate(account_id: UUID, session: DB, actor: Identity):
    account = owned_account(session, actor, account_id)
    if account.base_currency != "USD":
        raise HTTPException(422, "Hit rate currently requires a USD account")
    episodes, open_count = position_episodes(entries_for(session, account_id))
    today = datetime.now(ZoneInfo("America/New_York")).date()
    candidates = [e for e in episodes if not exclusion(e, today)]
    try:
        histories = {}
        if candidates:
            symbols = {market.symbol_for(e[0].security) for e in candidates} | set(BENCHMARKS)
            if len({e[0].security_id for e in candidates}) > 48:
                raise ValueError("Hit rate supports up to 48 securities plus SPY and QQQ")
            start = min(e[0].effective_date for e in candidates)
            end = max(e[-1].effective_date for e in candidates)
            with ThreadPoolExecutor(max_workers=6) as pool:
                histories = dict(
                    pool.map(lambda s: (s, market.history(s, start, end)), sorted(symbols))
                )
        with localcontext() as ctx:
            ctx.prec = 64
            result = calculate_hit_rate(episodes, open_count, histories, today)
        return wire(
            {
                **result,
                "fetched_at": datetime.now(UTC),
                "source": "Yahoo Finance daily history" if candidates else "Saved records",
            }
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except (OSError, KeyError, TypeError, IndexError, DecimalException) as exc:
        raise HTTPException(
            503, "Hit rate data is unavailable. Retry; saved records are unchanged."
        ) from exc
