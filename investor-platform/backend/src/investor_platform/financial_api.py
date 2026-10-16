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

from . import market
from .accounts import DB, Identity, owned_account
from .domain import completed_market_date
from .financial import Record, Row, records
from .financial_history import fund_listings, read_release
from .financial_history_report import build_report
from .ledger import LedgerView, entries_for, ledger_view
from .models import Account, LedgerEntry
from .valuation import latest, value_records

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
    """Use the same snapshot-date FX for both periods' company-share amounts."""
    result: dict[str, Decimal] = {"USD": Decimal(1)}
    proof: Record = {"USD": {"rate": "1", "quote_date": end.isoformat(), "source": "USD identity"}}
    currency: str
    for currency in currencies - {"USD"}:
        try:
            history: market.History
            if os.environ.get("TIINGO_API_KEY"):
                from .tiingo import fx_history

                try:
                    history = fx_history(
                        currency, end - timedelta(days=10), end, engine, workspace_id
                    )
                except OSError:
                    history = market.cached_history(
                        f"{currency}USD=X",
                        end - timedelta(days=10),
                        end,
                        instruments=("CURRENCY",),
                        engine=engine,
                        workspace_id=workspace_id,
                    )
            else:
                history = market.cached_history(
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
    session: DB,
    actor: Identity,
    year: Annotated[int, Query(ge=1900, le=9999)],
) -> Record:
    """Read actual account weights without changing ledger or reviewed financial records."""
    account: Account = owned_account(session, actor, account_id)
    today: date = completed_market_date()
    if year > today.year:
        raise HTTPException(422, "Select a completed or current calendar year")
    end: date = min(date(year, 12, 31), today)
    entries: list[LedgerEntry] = [
        e for e in entries_for(session, account_id) if e.effective_date <= end
    ]
    schema: str | None = getattr(request.app.state, "financial_schema", None)
    release: Record | None = None
    if schema:
        try:
            release = load_release(request.app.state.engine, schema)
        except ValueError:
            pass
        except (Error, SQLAlchemyError) as error:
            raise HTTPException(503, "Financial records are temporarily unavailable") from error
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
        return build_report(
            release,
            {
                "holdings_date": end.isoformat(),
                "base_currency": "USD",
                "synthetic": False,
                "holdings": [],
            },
            year,
            str(account_id),
            {"USD": Decimal(1)},
        )
    valuation: dict = value_records(
        ledger,
        account.base_currency,
        False,
        engine=request.app.state.engine,
        workspace_id=actor.workspace_id,
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
    rates, fx_proof = reporting_rates(currencies, end, request.app.state.engine, actor.workspace_id)
    result: Record = build_report(
        release,
        {
            "holdings_date": end.isoformat(),
            "base_currency": "USD",
            "synthetic": False,
            "holdings": holdings,
        },
        year,
        str(account_id),
        rates,
    )
    result["reporting_fx"] = fx_proof
    return result
