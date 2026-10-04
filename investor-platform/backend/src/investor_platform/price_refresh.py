"""Daily cache warming, with durable deduplication and bounded retries."""

import argparse
import hashlib
import json
import logging
from datetime import UTC, datetime, timedelta
from decimal import DecimalException
from enum import StrEnum

from dotenv import load_dotenv
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from . import market
from .db import LOCAL_WORKSPACE, make_engine
from .domain import MARKET_TIMEZONE, PRICE_REFRESH_TIME, Currency, completed_market_date
from .ledger import entries_for, ledger_view
from .models import Account, PriceRefreshRun
from .performance import holding_windows, period_securities
from .valuation import value_records

RETRY_DELAY = timedelta(minutes=30)
MAX_ATTEMPTS = 3
logger = logging.getLogger(__name__)


class RefreshStatus(StrEnum):
    RUNNING = "running"
    NOT_RUN = "not_run"
    COMPLETE = "complete"
    PARTIAL = "partial"
    AWAITING_CLOSE = "awaiting_close"


def scheduled_at(day):
    return datetime.combine(day, PRICE_REFRESH_TIME, MARKET_TIMEZONE)


def collect_account(session, account, day, refresh_after):
    entries = [e for e in entries_for(session, account.id) if e.effective_date <= day]
    if account.base_currency != Currency.USD or not entries:
        return None
    start = entries[0].effective_date
    securities = period_securities(entries)
    if len(securities) > market.MAX_SECURITIES or day - start > market.HISTORY_WINDOW:
        raise ValueError("Market history exceeds supported limits")
    provisional = bool(account.reconstruction)
    histories = market.security_histories(
        securities.values(),
        start,
        day,
        provisional=provisional,
        engine=session.get_bind(),
        workspace_id=account.workspace_id,
        windows=holding_windows(entries, securities, start, day, provisional=provisional),
        refresh_after=refresh_after,
    )
    close = min(max(histories[b].close) for b in market.BENCHMARKS)
    records = ledger_view(entries, account.base_currency)
    for security in securities.values():
        symbol = market.symbol_for(security, provisional=provisional)
        market.verify_exchange(security, histories[symbol], provisional=provisional)
    for holding in records.holdings:
        symbol = market.symbol_for(holding.security, provisional=provisional)
        if close not in histories[symbol].close:
            raise ValueError("Closing prices or same-date FX have not arrived")
    # Holdings use same-date Yahoo FX; warm that path as well as performance's Tiingo FX.
    valuation = value_records(
        records,
        account.base_currency,
        provisional,
        engine=session.get_bind(),
        workspace_id=account.workspace_id,
        refresh_after=refresh_after,
    )
    if not valuation["complete"]:
        raise ValueError("Some holding prices are unavailable")
    return close


def refresh_workspace(engine, workspace_id=LOCAL_WORKSPACE, *, now=None, force=False):
    now = (now or datetime.now(UTC)).astimezone(UTC)
    day = completed_market_date(now)
    tomorrow = scheduled_at(day + timedelta(days=1)).astimezone(UTC)
    identity = (workspace_id, day)
    with Session(engine) as session, session.begin():
        lock = int.from_bytes(
            hashlib.sha256(f"price-refresh:{identity}".encode()).digest()[:8], signed=True
        )
        if not session.scalar(text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": lock}):
            return {"status": RefreshStatus.RUNNING}, now + RETRY_DELAY
        run = session.get(PriceRefreshRun, identity)
        if run and not force:
            if run.report["status"] == RefreshStatus.COMPLETE or run.attempts >= MAX_ATTEMPTS:
                return run.report, tomorrow
            if now < run.attempted_at + RETRY_DELAY:
                return run.report, run.attempted_at + RETRY_DELAY
        attempts = run.attempts + 1 if run else 1
        report = {
            "status": RefreshStatus.COMPLETE,
            "date": day.isoformat(),
            "attempts": attempts,
            "collected": 0,
            "skipped": 0,
            "failed": 0,
            "latest_benchmark_close": None,
        }
        closes = []
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
        retry = report["status"] != RefreshStatus.COMPLETE and attempts < MAX_ATTEMPTS
        return report, min(now + RETRY_DELAY, tomorrow) if retry else tomorrow


def run_worker(engine, stop):
    while not stop.is_set():
        try:
            report, next_run = refresh_workspace(engine)
            logger.info("Daily prices: %s", json.dumps(report))
        except Exception:
            # A database outage must not kill the scheduler or print connection secrets.
            logger.error("Daily price collection unavailable; retrying in 30 minutes")
            next_run = datetime.now(UTC) + RETRY_DELAY
        stop.wait(max(1, (next_run - datetime.now(UTC)).total_seconds()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force", action="store_true", help="Retry now even if today’s run finished"
    )
    parser.add_argument(
        "--status", action="store_true", help="Read the most recent run without downloads"
    )
    args = parser.parse_args()
    load_dotenv(".env", override=False)
    engine = make_engine()
    try:
        if args.status:
            with Session(engine) as session:
                run = session.scalar(
                    select(PriceRefreshRun)
                    .where(PriceRefreshRun.workspace_id == LOCAL_WORKSPACE)
                    .order_by(PriceRefreshRun.scheduled_date.desc())
                    .limit(1)
                )
                report = run.report if run else {"status": RefreshStatus.NOT_RUN}
        else:
            report, _ = refresh_workspace(engine, force=args.force)
        print(json.dumps(report))
        if report["status"] == RefreshStatus.PARTIAL:
            raise SystemExit(1)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
