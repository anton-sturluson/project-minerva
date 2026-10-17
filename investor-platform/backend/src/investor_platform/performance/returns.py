"""Calculate account and stock returns from supplied prices."""

from decimal import Decimal
from typing import Literal

from fastapi import HTTPException

from investor_platform.domain import IN_KIND_ENTRIES, EntryKind, FundingStatus, IncomeKind
from investor_platform.ledger.accounting import ReplayState, replay
from investor_platform.market_data import listings as market_listings
from investor_platform.market_data import types as market_types
from investor_platform.models import LedgerEntry
from investor_platform.performance.attribution import StockAttribution
from investor_platform.performance.daily_returns import daily_return_factor
from investor_platform.performance.deposit_matched_benchmarks import funded_series
from investor_platform.performance.income import dividend_receivables, market_dividends
from investor_platform.performance.positions import period_securities
from investor_platform.performance.schemas import Baseline, BenchmarkMode, PerformanceScope
from investor_platform.performance.trade_matched_benchmarks import matched_series

ZERO = Decimal(0)


ONE = Decimal(1)


DAYS_PER_YEAR = Decimal("365.25")


ACCOUNT_CASH_METHODS: frozenset[str] = frozenset({"purchase_shortfall", "recorded"})


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
            symbol = market_listings.symbol_for(securities[sid], provisional=provisional)
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
            symbol = market_listings.symbol_for(entry.security, provisional=provisional)
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
    benchmark_mode=BenchmarkMode.BUY_HOLD,
    cash_method: str | None = None,
    dividend_policy: Literal["unrecorded_zero"] | None = None,
):
    """Link USD valuations on benchmark sessions; never zero-value missing positions."""
    include_opening_gain = (
        baseline == Baseline.HISTORY and bool(entries) and start <= entries[0].effective_date
    )
    stock_only = scope == PerformanceScope.STOCKS
    if stock_only:
        dividend_policy = None
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
        sid: histories[market_listings.symbol_for(s, provisional=provisional)]
        for sid, s in securities.items()
    }
    for sid, security in securities.items():
        market_listings.verify_exchange(security, prices[sid], provisional=provisional)
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
    known_account_cash: bool = cash_method in ACCOUNT_CASH_METHODS
    canonical_funding: bool = cash_method == "purchase_shortfall" and not any(
        entry.kind == EntryKind.OPENING_CASH for entry in entries
    )
    if not stock_only and funding_status == FundingStatus.INFERRED and not canonical_funding:
        warnings.append(
            "Cash history needs reconciliation; funding completeness is not confirmed."
            if cash_method == "recorded"
            else "Cash history needs reconciliation; starting funding was inferred."
        )
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
            assume_unrecorded_zero=dividend_policy == "unrecorded_zero",
        )
        warnings.extend(income_warnings)
    latest_holdings = []
    attribution = StockAttribution(securities) if stock_only else None
    replay_state: ReplayState = ReplayState()
    cursor: int = 0
    for d in days:
        first: int = cursor
        while cursor < len(entries) and entries[cursor].effective_date <= d:
            entry: LedgerEntry = entries[cursor]
            cursor += 1
            replay_state.apply(
                entry,
                day_end=cursor == len(entries)
                or entries[cursor].effective_date != entry.effective_date,
            )
        cash, lots = replay_state.cash, replay_state.lots
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
        # Full-history dollars include recorded executions before the first close.
        # The time-weighted index still begins at that close with no first-day return.
        interval = entries[:cursor] if previous is None and include_opening_gain else []
        denominator = ZERO
        if previous is not None:
            interval = entries[first:cursor]
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
            factor = daily_return_factor(previous, value + dividend, incoming, outgoing, in_kind)
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
    matched = None
    if benchmark_mode == BenchmarkMode.MATCHED:
        matched = matched_series(
            entries,
            histories,
            days,
            recorded=baseline == Baseline.RECORDED,
            provisional=provisional,
        )
        for row in values:
            for symbol in market_types.BENCHMARKS:
                row[symbol] = matched[row["date"]][symbol]["return"]
    funded: dict | None = None
    if benchmark_mode == BenchmarkMode.FUNDED_HOLD:
        if not known_account_cash or stock_only:
            raise ValueError("Deposit-matched indexes require a dated account cash history")
        funded = funded_series(entries, histories, days, provisional=provisional)
        row: dict
        symbol: str
        for row in values:
            for symbol in market_types.BENCHMARKS:
                row[symbol] = funded[row["date"]][symbol]["return"]
            row["benchmark_values"] = {
                symbol: funded[row["date"]][symbol]["value"] for symbol in market_types.BENCHMARKS
            }
    last = values[-1]
    result: dict = {
        **({"cash_method": cash_method} if cash_method else {}),
        **({"dividend_policy": dividend_policy} if dividend_policy else {}),
        **({"benchmark_values": funded[days[-1]]} if funded is not None else {}),
        "benchmark_mode": benchmark_mode,
        "matched_benchmarks": matched[days[-1]] if matched is not None else None,
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
            "Purchase-date deposits are inferred from recorded cash shortages; "
            "broker funding is not verified."
            if canonical_funding
            else "Recorded deposits and cash movements are used; no purchase funding is inferred."
            if cash_method == "recorded"
            else (
                "Testing estimate: opening shares and cash are inferred, "
                "not verified broker balances."
            ),
            "Assumes no missing trades or external flows; excluded import rows are not included.",
            "Uses exchange-specific listings and dated USD FX; confirm security identity.",
            (
                "Recorded dividends accrue on ex-dates and become cash on payment dates. "
                "Mismatched recorded income withholds returns; interest is recognized when posted."
                if dividend_policy
                else (
                    "Dividends accrue on their recorded ex-dates and become cash on payment dates. "
                    "Missing or mismatched distributions withhold returns; "
                    "interest is recognized when posted."
                )
            ),
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
            for key in ("portfolio", *market_types.BENCHMARKS)
        },
        "SPY": last["SPY"],
        "QQQ": last["QQQ"],
        "excess_spy": None if warnings else last["portfolio"] - last["SPY"],
        "excess_qqq": None if warnings else last["portfolio"] - last["QQQ"],
    }
    if dividend_policy:
        result["assumptions"].append(
            "Temporary assumption: unrecorded dividends are zero. "
            "Actual recorded dividends still count; returns may understate total return."
        )
    return result
