"""Read reviewed financial history using the selected account's dated equity holdings."""

import os
from datetime import date, timedelta
from decimal import Decimal, DecimalException
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from psycopg import Connection, Error
from psycopg.rows import RowFactory, dict_row
from sqlalchemy import Engine
from sqlalchemy.exc import SQLAlchemyError

from investor_platform.accounts import owned_account
from investor_platform.db import CurrentActor, DatabaseSession
from investor_platform.domain import completed_market_date
from investor_platform.financials.portfolio_report import add_portfolio_comparisons, build_report
from investor_platform.financials.reviewed_releases import fund_listings, read_release
from investor_platform.financials.types import Record, Row, records
from investor_platform.ledger.schemas import LedgerView
from investor_platform.ledger.state import active_entries_for_account, ledger_view
from investor_platform.market_data import types as market_types
from investor_platform.market_data import yahoo as market_yahoo
from investor_platform.models import Account, LedgerEntry
from investor_platform.performance.valuation import latest, value_records

router: APIRouter = APIRouter()


def load_release(engine: Engine, schema: str) -> Record | None:
    """Read one immutable release and restore the pooled connection's row factory."""
    with engine.connect().execution_options(
        isolation_level="REPEATABLE READ", postgresql_readonly=True
    ) as database:
        with database.begin():
            conn: Connection[Row] = cast(Connection[Row], database.connection.driver_connection)
            factory: RowFactory[Row] = conn.row_factory
            conn.row_factory = dict_row
            try:
                return read_release(conn, schema)
            finally:
                conn.row_factory = factory


def reporting_rates(
    currencies: set[str], end: date, engine: Engine, workspace_id: UUID
) -> tuple[dict[str, Decimal], Record]:
    """Use this snapshot's dated FX; company detail comparisons use the same rate."""
    result: dict[str, Decimal] = {"USD": Decimal(1)}
    proof: Record = {"USD": {"rate": "1", "quote_date": end.isoformat(), "source": "USD identity"}}
    currency: str
    for currency in currencies - {"USD"}:
        try:
            history: market_types.History
            if os.environ.get("TIINGO_API_KEY"):
                from investor_platform.market_data.tiingo import fx_history

                try:
                    history = fx_history(
                        currency, end - timedelta(days=10), end, engine, workspace_id
                    )
                except OSError:
                    history = market_yahoo.cached_history(
                        f"{currency}USD=X",
                        end - timedelta(days=10),
                        end,
                        instruments=("CURRENCY",),
                        engine=engine,
                        workspace_id=workspace_id,
                    )
            else:
                history = market_yahoo.cached_history(
                    f"{currency}USD=X",
                    end - timedelta(days=10),
                    end,
                    instruments=("CURRENCY",),
                    engine=engine,
                    workspace_id=workspace_id,
                )
            day: date
            rate: Decimal
            day, rate = latest(history, end)
            if rate.is_finite() and rate > 0:
                result[currency] = rate
                proof[currency] = {
                    "rate": format(rate, "f"),
                    "quote_date": day.isoformat(),
                    "source": history.source,
                }
        except (OSError, ValueError, KeyError, IndexError, TypeError, DecimalException):
            continue
    return result, proof


@router.get("/api/accounts/{account_id}/financials")
def financials(
    account_id: UUID,
    request: Request,
    session: DatabaseSession,
    actor: CurrentActor,
    year: Annotated[int, Query(ge=1900, le=9999)],
) -> Record:
    """Read actual account weights without changing ledger or reviewed financial records."""
    account: Account = owned_account(session, actor, account_id)
    today: date = completed_market_date()
    if year > today.year:
        raise HTTPException(422, "Select a completed or current calendar year")
    end: date = min(date(year, 12, 31), today)
    entries: list[LedgerEntry] = list(active_entries_for_account(session, account_id))
    schema: str | None = getattr(request.app.state, "financial_schema", None)
    release: Record | None = None
    if schema:
        try:
            release = load_release(request.app.state.engine, schema)
        except ValueError:
            pass
        except (Error, SQLAlchemyError) as error:
            raise HTTPException(503, "Financial records are temporarily unavailable") from error
    engine: Engine = request.app.state.engine
    result: Record = account_report(
        entries, account, release, year, end, engine, actor.workspace_id
    )
    prior: Record | None = None
    reason: str | None = None
    try:
        prior = account_report(
            entries, account, release, year - 1, date(year - 1, 12, 31), engine, actor.workspace_id
        )
    except HTTPException as error:
        if error.status_code != 503:
            raise
        reason = "Prior portfolio market prices unavailable"
    add_portfolio_comparisons(result, prior, year, reason=reason)
    return result


def account_report(
    entries: list[LedgerEntry],
    account: Account,
    release: Record | None,
    year: int,
    end: date,
    engine: Engine,
    workspace_id: UUID,
) -> Record:
    """Calculate one calendar snapshot using that year's actual holdings and FX."""
    entries = [entry for entry in entries if entry.effective_date <= end]
    ledger: LedgerView = ledger_view(entries, account.base_currency)
    funds: set[tuple[str, str]] = fund_listings(release)
    ledger = ledger.model_copy(
        update={
            "holdings": [
                holding
                for holding in ledger.holdings
                if (holding.security.ticker, holding.security.exchange) not in funds
            ]
        }
    )
    held_identities: set[tuple[str, str]] = {
        (holding.security.ticker, holding.security.exchange) for holding in ledger.holdings
    }
    matching: bool = release is not None and any(
        row["instrument_type"] == "company"
        and row["year"] == year
        and (str(row["ticker"]), str(row["exchange"])) in held_identities
        for row in records(release["records"])
    )
    if not matching:
        unavailable: Record = build_report(
            release,
            {
                "holdings_date": end.isoformat(),
                "base_currency": "USD",
                "synthetic": False,
                "holdings": [
                    {
                        "ticker": holding.security.ticker,
                        "exchange": holding.security.exchange,
                        "market_value": None,
                        "quote_date": None,
                    }
                    for holding in ledger.holdings
                ],
            },
            year,
            str(account.id),
            {"USD": Decimal(1)},
            pricing_complete=not ledger.holdings,
        )
        unavailable["availability_reason"] = "Reviewed financial data unavailable"
        return unavailable
    valuation: dict = value_records(
        ledger,
        account.base_currency,
        False,
        engine=engine,
        workspace_id=workspace_id,
        end=end,
    )
    if not valuation["complete"]:
        raise HTTPException(
            503,
            "Historical market prices are temporarily unavailable. "
            "Retry or check the security listing.",
        )
    holdings: list[Record] = [
        {
            "ticker": row["ticker"],
            "exchange": row["exchange"],
            "market_value": format(row["value"], "f") if row["value"] is not None else None,
            "quote_date": row["quote_date"].isoformat() if row["quote_date"] is not None else None,
        }
        for row in valuation["holdings"]
    ]
    held: set[tuple[str, str]] = {(str(h["ticker"]), str(h["exchange"])) for h in holdings}
    currencies: set[str] = (
        {
            str(row["currency"])
            for row in records(release["records"])
            if (str(row["ticker"]), str(row["exchange"])) in held and row["year"] == year
        }
        if release
        else set()
    )
    rates: dict[str, Decimal]
    fx_proof: Record
    rates, fx_proof = reporting_rates(currencies, end, engine, workspace_id)
    result: Record = build_report(
        release,
        {
            "holdings_date": end.isoformat(),
            "base_currency": "USD",
            "synthetic": False,
            "holdings": holdings,
        },
        year,
        str(account.id),
        rates,
    )
    result["reporting_fx"] = fx_proof
    return result
