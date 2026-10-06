"""Initialize and read shared financial inputs without touching portfolio tables."""

import json
import os
import re
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

from psycopg import Connection, sql
from psycopg import connect as pg_connect
from psycopg.rows import dict_row

type Value = str | int | float | bool | Decimal | date | datetime | UUID | list[str] | None
type Row = dict[str, Value]
type Dataset = dict[str, list[Row]]
type Report = dict[str, str | bool | dict[str, int]]

SCHEMA_VERSION: str = "minerva-financial-inputs-v2"
CORE_TABLES: tuple[str, ...] = ("companies", "metrics", "company_periods", "metric_values")


def connect(*, readonly: bool = True) -> Connection[Row]:
    """Require explicit financial credentials, with read-only transactions by default."""
    dsn: str | None = os.environ.get("INVESTOR_DATA_DATABASE_URL")
    if not dsn:
        raise ValueError("Set INVESTOR_DATA_DATABASE_URL explicitly; no database fallback is used")
    conn: Connection[Row] = pg_connect(
        dsn.replace("postgresql+psycopg://", "postgresql://", 1),
        row_factory=dict_row,
        connect_timeout=5,
    )
    conn.read_only = readonly
    return conn


def relation(schema: str, table: str) -> sql.Identifier:
    """Quote a table in the financial namespace; reject portfolio namespaces."""
    if not re.fullmatch(r"investor_data(?:_[a-z0-9]+)*", schema):
        raise ValueError("Use investor_data or an investor_data_<suffix> namespace")
    return sql.Identifier(schema, table)


def initialize(conn: Connection[Row], schema: str) -> None:
    """Create the reviewed schema atomically, leaving existing foreign schemas intact."""
    relation(schema, "companies")
    conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (schema,))
    existing: Row | None = conn.execute(
        "SELECT obj_description(oid, 'pg_namespace') AS version "
        "FROM pg_namespace WHERE nspname = %s",
        (schema,),
    ).fetchone()
    if existing:
        if existing["version"] != SCHEMA_VERSION:
            raise ValueError("Target namespace already exists without the expected schema version")
        return
    conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    ddl: str = Path(__file__).with_name("financial_schema.sql").read_text()
    conn.execute(sql.SQL(ddl).format(schema=sql.Identifier(schema)))
    conn.execute(
        sql.SQL("COMMENT ON SCHEMA {} IS {}").format(
            sql.Identifier(schema), sql.Literal(SCHEMA_VERSION)
        )
    )


def wire(value: Value) -> str:
    """Serialize dates, UUIDs and exact decimals without floating-point conversion."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime, UUID)):
        return str(value) if isinstance(value, UUID) else value.isoformat()
    raise TypeError(type(value).__name__)


def json_result(value: Dataset | Report | Row | list[Row]) -> str:
    """Return JSON for import receipts and read results."""
    return json.dumps(value, default=wire, ensure_ascii=False)


def source_id(company_id: int, reference: str) -> UUID:
    """Keep identical document labels from different companies separate."""
    return uuid5(NAMESPACE_URL, json.dumps([company_id, reference], ensure_ascii=False))


def company_rows(conn: Connection[Row], schema: str, ticker: str | None = None) -> list[Row]:
    """Return issuer matches without treating ticker symbols as unique identities."""
    query: sql.Composed = sql.SQL("SELECT * FROM {} ").format(relation(schema, "companies"))
    if ticker is not None:
        query += sql.SQL("WHERE ticker = %s ")
    return conn.execute(
        query + sql.SQL("ORDER BY id LIMIT 500"), (ticker,) if ticker is not None else ()
    ).fetchall()


def history_rows(
    conn: Connection[Row],
    schema: str,
    company_id: int,
    metric_key: str | None = None,
    scenario: str = "actual",
    limit: int = 100,
) -> list[Row]:
    """Read the latest bounded set of observations in chronological order."""
    if not 1 <= limit <= 500:
        raise ValueError("History limit must be between 1 and 500")
    query: sql.Composed = sql.SQL(
        "SELECT * FROM {} WHERE company_id = %s AND scenario = %s "
    ).format(relation(schema, "metric_values_flat"))
    parameters: list[Value] = [company_id, scenario]
    if metric_key is not None:
        query += sql.SQL("AND metric_key = %s ")
        parameters.append(metric_key)
    query += sql.SQL("ORDER BY period_end DESC, metric_key, id LIMIT %s")
    parameters.append(limit)
    rows: list[Row] = conn.execute(query, parameters).fetchall()
    return list(reversed(rows))


def grant_reader(conn: Connection[Row], schema: str, role: str) -> None:
    """Grant financial reads only to an existing dedicated non-administrator role."""
    relation(schema, "companies")
    if not re.fullmatch(r"investor_data_reader(?:_[a-z0-9]+)*", role):
        raise ValueError("Use a dedicated investor_data_reader role")
    capabilities: Row | None = conn.execute(
        "SELECT rolsuper, rolcreaterole, rolcreatedb FROM pg_roles WHERE rolname=%s",
        (role,),
    ).fetchone()
    if capabilities is None or any(capabilities.values()):
        raise ValueError("Create a dedicated non-administrator role first")
    conn.execute(
        sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(
            sql.Identifier(schema), sql.Identifier(role)
        )
    )
    table: str
    for table in (*CORE_TABLES, "sources", "metric_values_flat"):
        conn.execute(
            sql.SQL("GRANT SELECT ON {} TO {}").format(
                relation(schema, table), sql.Identifier(role)
            )
        )
