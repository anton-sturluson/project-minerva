"""Collect inputs and serve performance and trade statistics."""

from datetime import UTC, date, datetime
from decimal import Decimal, DecimalException, localcontext
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, Response

from investor_platform.accounts import owned_account
from investor_platform.api_responses import decimal_json_response
from investor_platform.db import CurrentActor, DatabaseSession
from investor_platform.domain import (
    ACCOUNTING_PRECISION,
    IN_KIND_ENTRIES,
    MARKET_TIMEZONE,
    Currency,
    EntryKind,
    FundingStatus,
    IncomeKind,
    completed_market_date,
)
from investor_platform.ledger.state import active_entries_for_account
from investor_platform.market_data import history as market
from investor_platform.market_data import types as market_types
from investor_platform.performance.minimum_funding_comparison import (
    build_minimum_funding_comparison,
)
from investor_platform.performance.positions import holding_windows, period_securities
from investor_platform.performance.report_cache import (
    CacheKey,
    cache_key,
    cached_report,
    remember_report,
)
from investor_platform.performance.returns import (
    ACCOUNT_CASH_METHODS,
    ONE,
    ZERO,
    annualized_return,
    calculate,
    scenario_entries,
)
from investor_platform.performance.schemas import (
    Baseline,
    BenchmarkMode,
    PerformanceRequest,
    PerformanceScope,
)
from investor_platform.performance.statistics import trade_statistics

router = APIRouter(prefix="/api/accounts")


@router.get("/{account_id}/statistics")
def statistics(account_id: UUID, session: DatabaseSession, actor: CurrentActor) -> Response:
    """Serve closed-position FIFO statistics for the owned account."""
    owned_account(session, actor, account_id)
    with localcontext() as ctx:
        ctx.prec = ACCOUNTING_PRECISION
        return decimal_json_response(
            trade_statistics(active_entries_for_account(session, account_id))
        )


@router.post("/{account_id}/performance")
def performance(
    account_id: UUID, period: PerformanceRequest, session: DatabaseSession, actor: CurrentActor
) -> Response:
    """Collect validated prices and serve the selected performance comparison."""
    account = owned_account(session, actor, account_id)
    provisional = bool(account.reconstruction)
    funding_status = FundingStatus.RECORDED
    if provisional:
        funding_status = FundingStatus(
            account.reconstruction.get("funding_status", FundingStatus.INFERRED)
        )
    entries = active_entries_for_account(session, account_id)
    if account.base_currency != Currency.USD:
        raise HTTPException(
            422,
            "Market comparisons currently require a USD account; FX conversion is not supported",
        )
    today = datetime.now(MARKET_TIMEZONE).date()
    if (
        period.start >= period.end
        or period.end > completed_market_date()
        or period.start < today - market_types.HISTORY_WINDOW
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
    report_key: CacheKey | None = None
    cash_method: str | None = (account.reconstruction or {}).get("cash_method")
    known_account_cash: bool = cash_method in ACCOUNT_CASH_METHODS
    canonical_funding: bool = cash_method == "purchase_shortfall"
    dividend_policy: Literal["unrecorded_zero"] | None = (
        "unrecorded_zero"
        if known_account_cash
        and (account.reconstruction or {}).get("dividend_policy") == "unrecorded_zero"
        else None
    )
    if canonical_funding and any(entry.kind == EntryKind.OPENING_CASH for entry in entries):
        raise HTTPException(
            422, "Purchase-date funding requires removal of the opening placeholder"
        )
    if period.anchor_date is not None and period.anchor_date >= period.end:
        raise HTTPException(422, "The comparison boundary must precede the ending date")
    funding_eligible: bool = (
        provisional
        and funding_status == FundingStatus.INFERRED
        and account.reconstruction.get("opening_cash") is not None
    )
    estimated: bool = not known_account_cash and (
        period.benchmark_mode == BenchmarkMode.FUNDED_HOLD
        or (
            funding_eligible
            and period.scope == PerformanceScope.ACCOUNT
            and period.benchmark_mode == BenchmarkMode.BUY_HOLD
        )
    )
    if estimated and not funding_eligible:
        raise HTTPException(422, "Minimum-funding estimates require an inferred-funding portfolio")
    if estimated and period.scope == PerformanceScope.ACCOUNT and period.exclude_security_ids:
        raise HTTPException(
            422, "Stock exclusions are unavailable in the minimum-funding comparison"
        )
    recorded = period.baseline == Baseline.RECORDED and not estimated and not known_account_cash
    fetch_start = period.start if recorded else entries[0].effective_date
    excluded = set(period.exclude_security_ids)
    try:
        if fetch_start < today - market_types.HISTORY_WINDOW:
            raise ValueError("This tracker supports ten years of ledger history")
        price_end = period.end
        if estimated:
            benchmarks = market.security_histories(
                [],
                fetch_start,
                period.end,
                engine=session.get_bind(),
                workspace_id=actor.workspace_id,
            )
            sessions = [d for d in benchmarks["SPY"].close if fetch_start <= d <= period.end]
            if not sessions:
                raise ValueError("Funding estimate needs completed benchmark sessions")
            price_end = max(sessions)
            if (period.end - price_end).days > 4:
                raise ValueError("Benchmark history is stale at the requested end date")
            entries = [
                e
                for e in entries
                if e.effective_date <= price_end
                or (e.income_kind == IncomeKind.DIVIDEND and e.accrual_date <= price_end)
            ]
        securities = period_securities(entries, period.start if recorded else None)
        if not excluded.issubset(securities):
            raise HTTPException(422, "Choose excluded stocks held during this comparison period")
        if len(securities) > market_types.MAX_SECURITIES:
            raise ValueError(
                f"This tracker supports up to {market_types.MAX_SECURITIES} securities "
                "and ten years of ledger history"
            )
        if (
            period.scope == PerformanceScope.STOCKS
            and period.benchmark_mode == BenchmarkMode.BUY_HOLD
            and period.baseline == Baseline.HISTORY
            and period.anchor_date is None
            and not period.exclude_security_ids
        ):
            report_key = cache_key(
                session, actor, account, entries, period.model_dump_json(), completed_market_date()
            )
            body: bytes | None = cached_report(report_key)
            if body is not None:
                return Response(body, media_type="application/json")
        # Full-history mode validates from inception; recorded mode trusts opening share units.
        fetched = market.security_histories(
            securities.values(),
            fetch_start,
            price_end,
            provisional=provisional,
            engine=session.get_bind(),
            workspace_id=actor.workspace_id,
            windows=holding_windows(
                entries, securities, fetch_start, price_end, provisional=provisional
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
                fetch_start if estimated else calculation_start,
                price_end,
                provisional=provisional,
                baseline=Baseline.HISTORY if estimated else period.baseline,
                funding_status=funding_status,
                scope=PerformanceScope.STOCKS if estimated else period.scope,
                benchmark_mode=BenchmarkMode.BUY_HOLD if estimated else period.benchmark_mode,
                cash_method=cash_method if known_account_cash else None,
                dividend_policy=dividend_policy,
            )
            if estimated:
                result = build_minimum_funding_comparison(
                    entries,
                    fetched,
                    result,
                    calculation_start,
                    provisional=provisional,
                    inferred_opening=Decimal(account.reconstruction["opening_cash"]),
                )
                if period.scope == PerformanceScope.STOCKS:
                    # Funding determines the index dollars, never the portfolio scope.
                    stock_result: dict = calculate(
                        entries,
                        fetched,
                        calculation_start,
                        price_end,
                        provisional=provisional,
                        baseline=period.baseline,
                        funding_status=funding_status,
                        scope=period.scope,
                    )
                    funded_points: dict[date, dict] = {
                        point["date"]: point for point in result["series"]
                    }
                    stock_point: dict
                    funded_point: dict | None
                    symbol: str
                    for stock_point in stock_result["series"]:
                        funded_point = funded_points.get(stock_point["date"])
                        for symbol in market_types.BENCHMARKS:
                            stock_point[symbol] = funded_point[symbol] if funded_point else ZERO
                        stock_point["benchmark_values"] = (
                            funded_point["benchmark_values"]
                            if funded_point
                            else dict.fromkeys(market_types.BENCHMARKS, ZERO)
                        )
                    field: str
                    for field in ("SPY", "QQQ", "benchmark_values", "funding_estimate"):
                        stock_result[field] = result[field]
                    result = stock_result
                result["benchmark_mode"] = period.benchmark_mode
                if period.benchmark_mode == BenchmarkMode.BUY_HOLD:
                    point: dict
                    symbol: str
                    for point in result["series"]:
                        for symbol in market_types.BENCHMARKS:
                            point[symbol] = (
                                fetched[symbol].adjusted[point["date"]]
                                / fetched[symbol].adjusted[result["start"]]
                                - ONE
                            )
                        point.pop("benchmark_values", None)
                    for symbol in market_types.BENCHMARKS:
                        result[symbol] = result["series"][-1][symbol]
                    result.pop("benchmark_values", None)
                    result["assumptions"] = [
                        assumption
                        for assumption in result["assumptions"]
                        if not assumption.startswith("Each index invests only")
                    ] + ["Each index is held from the displayed start; distributions reinvest."]
                for symbol in market_types.BENCHMARKS:
                    result[f"excess_{symbol.lower()}"] = (
                        None if result["return"] is None else result["return"] - result[symbol]
                    )
                result["cagr"] = {
                    key: annualized_return(
                        result[key] if key != "portfolio" else result["return"],
                        result["start"],
                        result["end"],
                    )
                    for key in ("portfolio", *market_types.BENCHMARKS)
                }
            else:
                result["baseline"] = period.baseline
            result["security_ids"] = list(securities)
            result["scenario"] = None
            result["scenario_error"] = None
            if (
                excluded
                and period.scope == PerformanceScope.ACCOUNT
                and funding_status == FundingStatus.INFERRED
                and not canonical_funding
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
                        cash_method=cash_method if known_account_cash else None,
                        dividend_policy=dividend_policy,
                    )
                    # Benchmark lines always describe the original stock deployments.
                    if period.benchmark_mode in {BenchmarkMode.MATCHED, BenchmarkMode.FUNDED_HOLD}:
                        scenario = result["scenario"]
                        scenario["benchmark_mode"] = period.benchmark_mode
                        scenario["matched_benchmarks"] = result["matched_benchmarks"]
                        if "benchmark_values" in result:
                            scenario["benchmark_values"] = result["benchmark_values"]
                        for original, alternative in zip(result["series"], scenario["series"]):
                            for symbol in market_types.BENCHMARKS:
                                alternative[symbol] = original[symbol]
                            if "benchmark_values" in original:
                                alternative["benchmark_values"] = original["benchmark_values"]
                        for symbol in market_types.BENCHMARKS:
                            scenario[symbol] = result[symbol]
                            scenario["cagr"][symbol] = result["cagr"][symbol]
                        scenario["excess_spy"] = (
                            None
                            if scenario["return"] is None
                            else scenario["return"] - result["SPY"]
                        )
                        scenario["excess_qqq"] = (
                            None
                            if scenario["return"] is None
                            else scenario["return"] - result["QQQ"]
                        )
                    result["scenario"]["excluded"] = [
                        {"id": sid, "ticker": s.ticker, "exchange": s.exchange}
                        for sid, s in securities.items()
                        if sid in excluded
                    ]
                except ValueError as exc:
                    result["scenario_error"] = str(exc)
        response: JSONResponse = decimal_json_response(
            {
                **result,
                "fetched_at": datetime.now(UTC),
                "source": " + ".join(
                    sorted({source for h in fetched.values() for source in h.source.split(" + ")})
                ),
            }
        )
        if (
            report_key is not None
            and not result.get("scenario_error")
            and not result.get("warnings")
        ):
            remember_report(report_key, bytes(response.body))
        return response
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except market_types.MarketDataError as exc:
        raise HTTPException(503, str(exc)) from exc
    except (OSError, KeyError, TypeError, IndexError, DecimalException) as exc:
        raise HTTPException(
            503,
            "Market data is unavailable or incomplete. "
            "Your ledger is unchanged; retry the comparison.",
        ) from exc
