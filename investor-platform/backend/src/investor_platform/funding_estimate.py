"""Assumption-based fresh-capital comparison; never creates ledger cash records."""

from bisect import bisect_left
from collections import defaultdict
from decimal import Decimal

from . import market
from .domain import IN_KIND_ENTRIES, EntryKind, IncomeKind
from .income import market_dividends

ZERO = Decimal(0)
ONE = Decimal(1)


def estimate(entries, histories, stock_report, start, *, provisional=False, inferred_opening=None):
    """Infer daily cash shortages, then invest that capital once in each index.

    Recorded sales and estimated gross dividends fund subsequent actual purchases.
    The index alternatives receive only fresh capital and never sell. Dividend cash
    is estimated on ex-dates; this is not a reconstruction of broker payment dates.
    """
    points = stock_report["series"]
    days = [p["date"] for p in points]
    end = days[-1]
    for entry in entries:
        relevant = entry.effective_date <= end or (
            entry.income_kind == IncomeKind.DIVIDEND and entry.accrual_date <= end
        )
        if not relevant:
            continue
        if entry.kind == EntryKind.OPENING_CASH:
            if inferred_opening is None or entry.amount != inferred_opening:
                raise ValueError("Funding estimate requires an explicitly inferred opening balance")
        elif entry.security_id is None:
            raise ValueError(
                "Funding estimate unavailable: recorded cash movements or income "
                "need a separate cash-flow comparison"
            )
    active = [e for e in entries if e.security_id is not None and e.effective_date <= end]
    if not active:
        raise ValueError("Funding estimate needs recorded stocks or trades")
    beginning = min(e.effective_date for e in active)
    points = [p for p in points if p["date"] >= beginning]
    days = [p["date"] for p in points]
    securities = {e.security_id: e.security for e in active}
    prices = {
        sid: histories[market.symbol_for(security, provisional=provisional)]
        for sid, security in securities.items()
    }
    dividends = market_dividends(active, prices, end)
    flows = defaultdict(Decimal)
    for entry in active:
        if entry.kind == EntryKind.BUY:
            flows[entry.effective_date] -= entry.amount
        elif entry.kind == EntryKind.SELL:
            flows[entry.effective_date] += entry.amount
    for (_, exdate), amount in dividends.items():
        flows[exdate] += amount

    def session(day):
        index = bisect_left(days, day)
        if index == len(days):
            raise ValueError("Funding contribution needs a completed benchmark session")
        return days[index]

    cash = ZERO
    cash_at_close = {}
    fresh = defaultdict(Decimal)
    # Net within each calendar date BEFORE mapping to sessions. A later Monday sale
    # cannot retroactively fund a Saturday purchase.
    for day, change in sorted(flows.items()):
        cash += change
        if cash < 0:
            fresh[session(day)] -= cash
            cash = ZERO
        cash_at_close[session(day)] = cash
    receipts = defaultdict(Decimal)
    for entry in active:
        if entry.kind in IN_KIND_ENTRIES:
            day = session(entry.effective_date)
            price = prices[entry.security_id].close.get(day)
            if price is None:
                raise ValueError("Funding estimate needs a received-position market value")
            receipts[day] += entry.quantity * price

    growth = dict.fromkeys(("portfolio", *market.BENCHMARKS), ONE)
    units = dict.fromkeys(market.BENCHMARKS, ZERO)
    previous = None
    cash = capital = ZERO
    all_points = []
    for point in points:
        day = point["date"]
        cash = cash_at_close.get(day, cash)
        contribution, receipt = fresh[day], receipts[day]
        capital += contribution + receipt
        wealth = {"portfolio": point["value"] + cash}
        if capital == 0 and wealth["portfolio"] > 0:
            raise ValueError(
                "Net same-day trades do not establish starting capital; intraday funding is needed"
            )
        for symbol in market.BENCHMARKS:
            price = histories[symbol].adjusted.get(day)
            if price is None or price <= 0:
                raise ValueError(f"Funding estimate needs a valid {symbol} close on {day}")
            units[symbol] += (contribution + receipt) / price
            wealth[symbol] = units[symbol] * price
        if previous is not None:
            for key in growth:
                denominator = previous[key] + contribution
                factor = (wealth[key] - receipt) / denominator if denominator else ONE
                if factor < 0:
                    raise ValueError("Funding estimate has an invalid daily return factor")
                growth[key] *= factor
        all_points.append(
            {
                "date": day,
                "value": wealth["portfolio"],
                "cash": cash,
                "receivables": ZERO,
                **growth,
                "benchmark_values": {s: wealth[s] for s in market.BENCHMARKS},
            }
        )
        previous = wealth
    selected = [p for p in all_points if p["date"] >= start]
    if len(selected) < 2:
        raise ValueError("Funding comparison needs at least two displayed sessions")
    bases = {key: selected[0][key] for key in growth}
    for point in selected:
        for key, base in bases.items():
            if base <= 0:
                raise ValueError("Funding return is undefined after a total loss")
            point[key] = point[key] / base - ONE
    last = selected[-1]
    return {
        **stock_report,
        "scope": "account",
        "provisional": True,
        "baseline": "history",
        "benchmark_mode": "funded_hold",
        "matched_benchmarks": None,
        "attribution": None,
        "series": selected,
        "start": selected[0]["date"],
        "holdings": [
            {**holding, "weight": holding["value"] / last["value"] if last["value"] else None}
            for holding in stock_report["holdings"]
        ],
        "end": last["date"],
        "value": last["value"],
        "cash": last["cash"],
        "return": last["portfolio"],
        "SPY": last["SPY"],
        "QQQ": last["QQQ"],
        "excess_spy": last["portfolio"] - last["SPY"],
        "excess_qqq": last["portfolio"] - last["QQQ"],
        "benchmark_values": {
            symbol: {
                "value": last["benchmark_values"][symbol],
                "gain": last["benchmark_values"][symbol] - capital,
            }
            for symbol in market.BENCHMARKS
        },
        "funding_estimate": {
            "start": days[0],
            "capital": capital,
            "fresh_cash": sum(fresh.values(), ZERO),
            "received_assets": sum(receipts.values(), ZERO),
            "estimated_dividends": sum(dividends.values(), ZERO),
            "income_policy": "provider_gross_on_ex_date",
        },
        "assumptions": [
            "Minimum funding: same-day net sales and estimated gross dividends fund buys first.",
            "Fresh cash covers remaining shortages; inferred opening cash is ignored.",
            "Gross dividends are estimated cash on ex-dates; payment dates and taxes are unknown.",
            "Received shares contribute their closing market value once.",
            "Each index invests only that fresh capital and never sells; distributions reinvest.",
            "Actual estimated value includes modeled cash; recorded broker cash is unchanged.",
        ],
    }
