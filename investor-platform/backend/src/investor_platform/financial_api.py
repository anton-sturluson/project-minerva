"""Read reviewed annual company facts with explicitly illustrative equity weights."""

from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from psycopg import Connection, Error
from psycopg.rows import RowFactory, dict_row
from sqlalchemy import Engine
from sqlalchemy.exc import SQLAlchemyError

from .db import Actor, get_actor
from .financial import Record, Row, check_schema, record, records, relation, show
from .weighted_financial import add_per_share_comparisons, build_weighted_report

router: APIRouter = APIRouter()
PILOT_HOLDINGS: tuple[tuple[str, str, str], ...] = (
    ("sec-cik:0001652044", "GOOGL", "60"),
    ("sec-cik:0001568651", "OSCR", "25"),
    ("sec-cik:0000880984", "ACFN", "15"),
)
SUPPORTED_YEARS: tuple[int, ...] = (2023, 2024, 2025)


def pilot_snapshot(year: int) -> Record:
    """Declare illustrative weights without implying actual holdings or historical quotes."""
    return {
        "holdings_date": f"{year}-12-31",
        "base_currency": "USD",
        "synthetic": True,
        "source": "Explicit illustrative equity weights represented as nominal USD values; "
        "not actual portfolio exposure or historical market quotes",
        "holdings": [
            {"issuer_key": issuer, "ticker": ticker, "market_value": value}
            for issuer, ticker, value in PILOT_HOLDINGS
        ],
    }


def read_profiles(
    engine: Engine, schema: str, year: int, *, include_prior: bool = False
) -> list[Record]:
    """Read one consistent read-only snapshot using the application's existing engine."""
    relation(schema, "publications")
    profiles: list[Record] = []
    with engine.connect().execution_options(
        isolation_level="REPEATABLE READ", postgresql_readonly=True
    ) as database:
        with database.begin():
            conn: Connection[Row] = cast(Connection[Row], database.connection.driver_connection)
            prior_factory: RowFactory[Row] = conn.row_factory
            conn.row_factory = dict_row
            try:
                check_schema(conn, schema)
                issuer: str
                ticker: str
                value: str
                selected_year: int
                for selected_year in (year, year - 1) if include_prior else (year,):
                    for issuer, ticker, value in PILOT_HOLDINGS:
                        try:
                            profiles.append(show(conn, schema, issuer, selected_year))
                        except ValueError:
                            continue
            finally:
                conn.row_factory = prior_factory
    return profiles


@router.get("/api/financials")
def financials(
    request: Request,
    actor: Annotated[Actor, Depends(get_actor)],
    year: Annotated[int, Query(ge=2023, le=2025)] = 2025,
) -> Record:
    """Return the pilot report, honest missing-data states or a recoverable transport error."""
    schema: str | None = getattr(request.app.state, "financial_schema", None)
    profiles: list[Record] = []
    reason: str | None = None
    if not schema:
        reason = "Annual financial data is not configured. Set the reviewed pilot namespace."
    else:
        try:
            profiles = read_profiles(request.app.state.engine, schema, year, include_prior=True)
        except ValueError:
            reason = "The configured financial namespace is missing or unsupported. "
            reason += "Import reviewed annual data into an explicit financial namespace."
        except (Error, SQLAlchemyError) as error:
            raise HTTPException(
                status_code=503,
                detail="Annual financial records are temporarily unavailable. "
                "Check the database connection and read permissions, then retry.",
            ) from error
    selected: list[Record] = [
        p for p in profiles if str(record(p["period"])["end"])[:4] == str(year)
    ]
    previous: list[Record] = [p for p in profiles if p not in selected]
    result: Record = build_weighted_report(pilot_snapshot(year), selected)
    add_per_share_comparisons(result, build_weighted_report(pilot_snapshot(year - 1), previous))
    eligible: int = sum(
        company["financial_status"] == "eligible" for company in records(result["companies"])
    )
    result["api_status"] = (
        "available" if eligible == len(PILOT_HOLDINGS) else "partial" if eligible else "unavailable"
    )
    result["availability_reason"] = reason or (
        None
        if eligible == len(PILOT_HOLDINGS)
        else "Some annual company profiles are missing or unreviewed. "
        "Coverage shows available data."
    )
    result["supported_years"] = list(SUPPORTED_YEARS)
    return result
