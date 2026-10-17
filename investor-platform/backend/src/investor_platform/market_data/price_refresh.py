"""Daily cache warming, with durable deduplication and bounded retries."""

import argparse
import hashlib
import json
import logging
from datetime import UTC, date, datetime, timedelta
from decimal import DecimalException
from enum import StrEnum
from threading import Event
from typing import NotRequired, TypedDict, cast
from uuid import UUID

from dotenv import load_dotenv
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from investor_platform.db import LOCAL_WORKSPACE, make_engine
from investor_platform.domain import (
    MARKET_TIMEZONE,
    PRICE_REFRESH_TIME,
    Currency,
    completed_market_date,
)
from investor_platform.ledger.schemas import HoldingView, LedgerView
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


def scheduled_at(day: date) -> datetime:
    """Return the New York closing collection time on a calendar day."""
    return datetime.combine(day, PRICE_REFRESH_TIME, MARKET_TIMEZONE)


def collect_account(
    session: Session, account: Account, day: date, refresh_after: datetime
) -> date | None:
    """Warm account histories and confirm that held listings have complete closing prices."""
    entries: list[LedgerEntry] = [
        e for e in active_entries_for_account(session, account.id) if e.effective_date <= day
    ]
    if account.base_currency != Currency.USD or not entries:
        return None
    start: date = entries[0].effective_date
    securities: dict[UUID, Security] = period_securities(entries)
    if len(securities) > market_types.MAX_SECURITIES or day - start > market_types.HISTORY_WINDOW:
        raise ValueError("Market history exceeds supported limits")
    provisional: bool = bool(account.reconstruction)
    histories: dict[str, market_types.History] = market.security_histories(
        securities.values(),
        start,
        day,
        provisional=provisional,
        engine=session.get_bind(),
        workspace_id=account.workspace_id,
        windows=holding_windows(entries, securities, start, day, provisional=provisional),
        refresh_after=refresh_after,
    )
    close: date = min(max(histories[b].close) for b in market_types.BENCHMARKS)
    records: LedgerView = ledger_view(entries, account.base_currency)
    security: Security
    symbol: str
    for security in securities.values():
        symbol = market_listings.symbol_for(security, provisional=provisional)
        market_listings.verify_exchange(security, histories[symbol], provisional=provisional)
    holding: HoldingView
    for holding in records.holdings:
        symbol = market_listings.symbol_for(holding.security, provisional=provisional)
        if close not in histories[symbol].close:
            raise ValueError("Closing prices or same-date FX have not arrived")
    # Holdings use same-date Yahoo FX; warm that path as well as performance's Tiingo FX.
    valuation_complete: bool = value_records(
        records,
        account.base_currency,
        provisional,
        engine=session.get_bind(),
        workspace_id=account.workspace_id,
        refresh_after=refresh_after,
    )["complete"]
    if not valuation_complete:
        raise ValueError("Some holding prices are unavailable")
    return close


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
    session: Session
    with Session(engine) as session, session.begin():
        lock: int = int.from_bytes(
            hashlib.sha256(f"price-refresh:{identity}".encode()).digest()[:8], signed=True
        )
        if not session.scalar(text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": lock}):
            return {"status": RefreshStatus.RUNNING}, now + RETRY_DELAY
        run: PriceRefreshRun | None = session.get(PriceRefreshRun, identity)
        if run and not force:
            if run.report["status"] == RefreshStatus.COMPLETE or run.attempts >= MAX_ATTEMPTS:
                return cast(RefreshReport, run.report), tomorrow
            if now < run.attempted_at + RETRY_DELAY:
                return cast(RefreshReport, run.report), run.attempted_at + RETRY_DELAY
        attempts: int = run.attempts + 1 if run else 1
        report: RefreshReport = {
            "status": RefreshStatus.COMPLETE,
            "date": day.isoformat(),
            "attempts": attempts,
            "collected": 0,
            "skipped": 0,
            "failed": 0,
            "latest_benchmark_close": None,
        }
        closes: list[date] = []
        account: Account
        close: date | None
        for account in session.scalars(select(Account).where(Account.workspace_id == workspace_id)):
            try:
                close = collect_account(session, account, day, now)
                if close is None:
                    report["skipped"] += 1
                else:
                    report["collected"] += 1
                    closes.append(close)
            except (OSError, ValueError, KeyError, TypeError, IndexError, DecimalException):
                # Keep provider payloads, tokens and account identities out of operational logs.
                report["failed"] += 1
        if closes:
            report["latest_benchmark_close"] = min(closes).isoformat()
        if report["failed"]:
            report["status"] = RefreshStatus.PARTIAL
        elif closes and day.weekday() < 5 and min(closes) < day:
            # Providers can publish late. Holidays also get bounded follow-up attempts.
            report["status"] = RefreshStatus.AWAITING_CLOSE
        if run is None:
            run = PriceRefreshRun(workspace_id=workspace_id, scheduled_date=day)
            session.add(run)
        run.attempted_at, run.attempts, run.report = now, attempts, report
        retry: bool = report["status"] != RefreshStatus.COMPLETE and attempts < MAX_ATTEMPTS
        return report, min(now + RETRY_DELAY, tomorrow) if retry else tomorrow


def run_worker(engine: Engine, stop: Event) -> None:
    """Run collection until stopped, retaining retries through temporary database outages."""
    report: RefreshReport
    next_run: datetime
    while not stop.is_set():
        try:
            report, next_run = refresh_workspace(engine)
            logger.info("Daily prices: %s", json.dumps(report))
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
