"""Daily cache warming, with durable deduplication and bounded retries."""

import argparse
import hashlib
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import DecimalException
from enum import StrEnum
from threading import Event
from typing import NotRequired, TypedDict, cast
from uuid import UUID

from dotenv import load_dotenv
from fastapi import APIRouter, Request
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from investor_platform.db import LOCAL_WORKSPACE, CurrentActor, DatabaseSession, make_engine
from investor_platform.domain import (
    MARKET_TIMEZONE,
    PRICE_REFRESH_TIME,
    Currency,
    completed_market_date,
)
from investor_platform.ledger.schemas import LedgerView, SecurityView
from investor_platform.ledger.state import active_entries_for_account, ledger_view
from investor_platform.market_data import history as market
from investor_platform.market_data import listings as market_listings
from investor_platform.market_data import types as market_types
from investor_platform.models import Account, LedgerEntry, PriceRefreshRun, Security
from investor_platform.performance.positions import holding_windows, period_securities
from investor_platform.performance.valuation import value_records

RETRY_DELAY: timedelta = timedelta(minutes=30)
MAX_ATTEMPTS: int = 3
logger: logging.Logger = logging.getLogger(__name__)


class RefreshStatus(StrEnum):
    """Durable outcomes of one scheduled workspace price collection."""

    RUNNING = "running"
    NOT_RUN = "not_run"
    INTERRUPTED = "interrupted"
    COMPLETE = "complete"
    PARTIAL = "partial"
    AWAITING_CLOSE = "awaiting_close"


class RefreshReport(TypedDict):
    """Collection outcome with optional counters for skipped or not-yet-run work."""

    status: str
    date: NotRequired[str]
    attempts: NotRequired[int]
    collected: NotRequired[int]
    skipped: NotRequired[int]
    failed: NotRequired[int]
    latest_benchmark_close: NotRequired[str | None]
    failures: NotRequired[list[dict[str, str]]]
    last_success_at: NotRequired[str | None]


def scheduled_at(day: date) -> datetime:
    """Return the New York closing collection time on a calendar day."""
    return datetime.combine(day, PRICE_REFRESH_TIME, MARKET_TIMEZONE)


@dataclass
class AccountCollection:
    """Independent current-price and historical-window collection outcomes."""

    close: date | None = None
    failures: list[dict[str, str]] = field(default_factory=list)
    skipped: bool = False


def collect_account(
    session: Session, account: Account, day: date, refresh_after: datetime
) -> AccountCollection:
    """Warm current prices even when an unrelated historical listing is unavailable."""
    entries: list[LedgerEntry] = [
        e for e in active_entries_for_account(session, account.id) if e.effective_date <= day
    ]
    result: AccountCollection = AccountCollection()
    if account.base_currency != Currency.USD or not entries:
        result.skipped = True
        return result
    start: date = entries[0].effective_date
    provisional: bool = bool(account.reconstruction)
    records: LedgerView = ledger_view(entries, account.base_currency)
    valuation: dict = value_records(
        records,
        account.base_currency,
        provisional,
        engine=session.get_bind(),
        workspace_id=account.workspace_id,
        refresh_after=refresh_after,
        end=day,
    )
    for row in valuation["holdings"]:
        if row["price_error"]:
            result.failures.append(
                {"symbol": row["ticker"], "scope": "current", "reason": "price_unavailable"}
            )
    securities: dict[UUID, Security] = period_securities(entries)
    if len(securities) > market_types.MAX_SECURITIES or day - start > market_types.HISTORY_WINDOW:
        result.failures.append({"symbol": "", "scope": "history", "reason": "history_limit"})
        return result
    windows: dict[str, tuple[date, date]] = holding_windows(
        entries, securities, start, day, provisional=provisional
    )
    closes: list[date] = []
    for symbol in market_types.BENCHMARKS:
        try:
            history: market_types.History = market.market_yahoo.cached_history(
                symbol,
                start - market_types.MAX_CLOSE_AGE,
                day,
                engine=session.get_bind(),
                workspace_id=account.workspace_id,
                refresh_after=refresh_after,
            )
            closes.append(max(history.close))
        except (OSError, ValueError, KeyError, TypeError, IndexError, DecimalException):
            result.failures.append(
                {"symbol": symbol, "scope": "history", "reason": "history_unavailable"}
            )
    if len(closes) == len(market_types.BENCHMARKS):
        result.close = min(closes)
    current: set[UUID] = {holding.security.id for holding in records.holdings}
    engine: Engine = session.get_bind()
    workspace_id: UUID = account.workspace_id
    listings: list[SecurityView] = [SecurityView.model_validate(s) for s in securities.values()]

    def collect_listing(security: SecurityView) -> dict[str, str] | None:
        """Collect one independent history window without sharing a database session."""
        symbol: str = security.ticker
        try:
            symbol = market_listings.symbol_for(security, provisional=provisional)
            first, last = windows.get(symbol, (start, day))
            history = market.listing_history(
                security,
                first,
                last,
                provisional=provisional,
                engine=engine,
                workspace_id=workspace_id,
                refresh_after=refresh_after,
            )
            foreign: tuple[str, str, set[str]] | None = market_listings.FOREIGN_LISTINGS.get(
                security.exchange
            )
            if foreign:
                fx: market_types.History = market.fx_history(
                    foreign[1],
                    first - market_types.MAX_CLOSE_AGE,
                    last,
                    engine=engine,
                    workspace_id=workspace_id,
                    refresh_after=refresh_after,
                )
                history = market.usd_history(history, fx)
            if not history.close or (
                security.id in current and result.close and result.close not in history.close
            ):
                raise ValueError("Closing price or same-date FX unavailable")
        except (OSError, ValueError, KeyError, TypeError, IndexError, DecimalException):
            return {"symbol": symbol, "scope": "history", "reason": "history_unavailable"}
        return None

    with ThreadPoolExecutor(max_workers=6) as pool:
        result.failures.extend(
            failure for failure in pool.map(collect_listing, listings) if failure
        )
    return result


def refresh_workspace(
    engine: Engine,
    workspace_id: UUID = LOCAL_WORKSPACE,
    *,
    now: datetime | None = None,
    force: bool = False,
) -> tuple[RefreshReport, datetime]:
    """Collect one workspace with durable deduplication and a bounded next retry time."""
    now = (now or datetime.now(UTC)).astimezone(UTC)
    day: date = completed_market_date(now)
    tomorrow: datetime = scheduled_at(day + timedelta(days=1)).astimezone(UTC)
    identity: tuple[UUID, date] = (workspace_id, day)
    lock: int = int.from_bytes(
        hashlib.sha256(f"price-refresh:{workspace_id}".encode()).digest()[:8], signed=True
    )
    # A connection-owned lock survives commits, but is released when the process dies.
    with engine.connect() as connection:
        acquired: bool = bool(
            connection.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": lock})
        )
        connection.commit()
        if not acquired:
            return {"status": RefreshStatus.RUNNING}, now + RETRY_DELAY
        try:
            with Session(engine) as session:
                run: PriceRefreshRun | None = session.get(PriceRefreshRun, identity)
                if run and run.report["status"] == RefreshStatus.RUNNING:
                    run.report = {**run.report, "status": RefreshStatus.INTERRUPTED}
                    session.commit()
                if run and not force:
                    if (
                        run.report["status"] == RefreshStatus.COMPLETE
                        or run.attempts >= MAX_ATTEMPTS
                    ):
                        return cast(RefreshReport, run.report), tomorrow
                    if now < run.attempted_at + RETRY_DELAY:
                        return cast(RefreshReport, run.report), run.attempted_at + RETRY_DELAY
                previous: PriceRefreshRun | None = session.scalar(
                    select(PriceRefreshRun)
                    .where(PriceRefreshRun.workspace_id == workspace_id)
                    .order_by(PriceRefreshRun.scheduled_date.desc())
                    .limit(1)
                )
                last_success: str | None = last_success_at(session, workspace_id, previous)
                attempts: int = run.attempts + 1 if run else 1
                report: RefreshReport = {
                    "status": RefreshStatus.RUNNING,
                    "date": day.isoformat(),
                    "attempts": attempts,
                    "collected": 0,
                    "skipped": 0,
                    "failed": 0,
                    "latest_benchmark_close": None,
                    "failures": [],
                    "last_success_at": last_success,
                }
                if run is None:
                    run = PriceRefreshRun(workspace_id=workspace_id, scheduled_date=day)
                    session.add(run)
                run.attempted_at, run.attempts, run.report = now, attempts, dict(report)
                session.commit()
                closes: list[date] = []
                for account in session.scalars(
                    select(Account).where(Account.workspace_id == workspace_id)
                ):
                    try:
                        outcome: AccountCollection = collect_account(session, account, day, now)
                        if outcome.skipped:
                            report["skipped"] += 1
                        elif outcome.failures:
                            report["failed"] += 1
                            report["failures"].extend(outcome.failures)
                        else:
                            report["collected"] += 1
                        if outcome.close is not None:
                            closes.append(outcome.close)
                    except (OSError, ValueError, KeyError, TypeError, IndexError, DecimalException):
                        report["failed"] += 1
                        report["failures"].append(
                            {"symbol": "", "scope": "account", "reason": "collection_unavailable"}
                        )
                report["status"] = RefreshStatus.COMPLETE
                if closes:
                    report["latest_benchmark_close"] = min(closes).isoformat()
                if report["failed"]:
                    report["status"] = RefreshStatus.PARTIAL
                elif closes and day.weekday() < 5 and min(closes) < day:
                    report["status"] = RefreshStatus.AWAITING_CLOSE
                if report["status"] == RefreshStatus.COMPLETE:
                    report["last_success_at"] = now.isoformat()
                run.report = dict(report)
                session.commit()
                retry: bool = report["status"] != RefreshStatus.COMPLETE and attempts < MAX_ATTEMPTS
                return report, min(now + RETRY_DELAY, tomorrow) if retry else tomorrow
        finally:
            try:
                connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": lock})
                connection.commit()
            except Exception:
                connection.invalidate()
                raise


def last_success_at(
    session: Session, workspace_id: UUID, latest: PriceRefreshRun | None
) -> str | None:
    """Retain the last complete collection across failures and pre-status run records."""
    if latest and latest.report.get("last_success_at"):
        return latest.report["last_success_at"]
    successful: PriceRefreshRun | None = session.scalar(
        select(PriceRefreshRun)
        .where(
            PriceRefreshRun.workspace_id == workspace_id,
            PriceRefreshRun.report["status"].as_string() == RefreshStatus.COMPLETE,
        )
        .order_by(PriceRefreshRun.scheduled_date.desc())
        .limit(1)
    )
    return successful.attempted_at.isoformat() if successful else None


router: APIRouter = APIRouter(prefix="/api/market-data", tags=["market data"])


@router.get("/status")
def collection_status(request: Request, session: DatabaseSession, actor: CurrentActor) -> dict:
    """Read worker liveness and persisted outcomes without requesting provider data."""
    now: datetime = datetime.now(UTC)
    run: PriceRefreshRun | None = session.scalar(
        select(PriceRefreshRun)
        .where(PriceRefreshRun.workspace_id == actor.workspace_id)
        .order_by(PriceRefreshRun.scheduled_date.desc())
        .limit(1)
    )
    enabled: bool = request.app.state.daily_prices
    worker = getattr(request.app.state, "price_worker", None)
    next_due: datetime | None = None
    last_success: str | None = last_success_at(session, actor.workspace_id, run)
    if enabled:
        if run is None:
            next_due = now
        elif run.report["status"] != RefreshStatus.COMPLETE and run.attempts < MAX_ATTEMPTS:
            next_due = min(
                run.attempted_at + RETRY_DELAY, scheduled_at(run.scheduled_date + timedelta(days=1))
            )
        else:
            next_due = scheduled_at(run.scheduled_date + timedelta(days=1))
    return {
        "enabled": enabled,
        "worker_alive": worker is not None and worker.is_alive(),
        "last_attempt_at": run.attempted_at.isoformat() if run else None,
        "last_success_at": last_success,
        "next_due_at": next_due.isoformat() if next_due else None,
        "report": {"failures": [], **run.report} if run else None,
        "release": request.app.state.release,
    }


def run_worker(engine: Engine, stop: Event) -> None:
    """Run collection until stopped, retaining retries through temporary database outages."""
    report: RefreshReport
    next_run: datetime
    while not stop.is_set():
        try:
            report, next_run = refresh_workspace(engine)
            logger.info(
                "Daily prices: %s", json.dumps({k: v for k, v in report.items() if k != "failures"})
            )
        except Exception:
            # A database outage must not kill the scheduler or print connection secrets.
            logger.error("Daily price collection unavailable; retrying in 30 minutes")
            next_run = datetime.now(UTC) + RETRY_DELAY
        stop.wait(max(1, (next_run - datetime.now(UTC)).total_seconds()))


def main() -> None:
    """Read collection status or run an explicit price-cache refresh."""
    parser: argparse.ArgumentParser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force", action="store_true", help="Retry now even if today’s run finished"
    )
    parser.add_argument(
        "--status", action="store_true", help="Read the most recent run without downloads"
    )
    args: argparse.Namespace = parser.parse_args()
    load_dotenv(".env", override=False)
    engine: Engine = make_engine()
    report: RefreshReport
    session: Session
    _: datetime
    try:
        if args.status:
            with Session(engine) as session:
                run: PriceRefreshRun | None = session.scalar(
                    select(PriceRefreshRun)
                    .where(PriceRefreshRun.workspace_id == LOCAL_WORKSPACE)
                    .order_by(PriceRefreshRun.scheduled_date.desc())
                    .limit(1)
                )
                report = (
                    cast(RefreshReport, run.report) if run else {"status": RefreshStatus.NOT_RUN}
                )
        else:
            report, _ = refresh_workspace(engine, force=args.force)
        print(json.dumps(report))
        if report["status"] == RefreshStatus.PARTIAL:
            raise SystemExit(1)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
