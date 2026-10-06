"""Import a read-only, WAL-consistent SQLite snapshot and verify every mapped field."""

import hashlib
import json
import math
import sqlite3
from contextlib import closing
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast

from psycopg import Connection, sql
from psycopg.types.json import Jsonb

from .financial_store import (
    CORE_TABLES,
    Dataset,
    Report,
    Row,
    Value,
    initialize,
    json_result,
    relation,
    source_id,
)

SOURCE_COLUMNS: dict[str, frozenset[str]] = {
    "companies": frozenset(
        (
            "id ticker name sector created_at updated_at description "
            "categories folder_exists exchange"
        ).split()
    ),
    "metrics": frozenset(
        "id metric_key display_name description value_type created_at updated_at".split()
    ),
    "company_periods": frozenset(
        (
            "id company_id period_kind fiscal_year fiscal_quarter fiscal_label "
            "period_start period_end created_at updated_at"
        ).split()
    ),
    "metric_values": frozenset(
        (
            "id metric_id period_id value value_high value_status qualifier scenario origin "
            "currency_code reported_text source_ref calculation_note created_at updated_at"
        ).split()
    ),
}


def normalize(table: str, row: sqlite3.Row) -> Row:
    """Preserve legacy representations while converting dates, decimals and metadata."""
    result: Row = dict(row)
    key: str
    value: Value
    for key, value in result.items():
        if value is None:
            continue
        if key in {"period_start", "period_end"}:
            result[key] = date.fromisoformat(str(value))
        elif key in {"created_at", "updated_at"}:
            stamp: datetime = datetime.fromisoformat(str(value))
            result[key] = stamp.replace(tzinfo=UTC) if stamp.tzinfo is None else stamp
        elif key in {"value", "value_high"}:
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError("Legacy observations must be finite")
            result[key] = Decimal(str(value))
    if table == "companies":
        if result["categories"] is not None:
            categories: list[str] = json.loads(str(result["categories"]))
            if not isinstance(categories, list) or not all(isinstance(x, str) for x in categories):
                raise ValueError("Legacy categories must be a JSON array of strings")
            result["categories"] = categories
        if result["folder_exists"] not in {0, 1}:
            raise ValueError("Legacy folder flag must be zero or one")
        result["folder_exists"] = bool(result["folder_exists"])
    if table == "metric_values":
        result.update(source_id=None, verification_status="legacy_unverified")
    return result


def read_legacy(path: Path) -> Dataset:
    """Read committed WAL records without writing or checkpointing the source."""
    path = path.resolve(strict=True)
    dataset: Dataset = {}
    temporary: str
    source: sqlite3.Connection
    destination: sqlite3.Connection
    conn: sqlite3.Connection
    with TemporaryDirectory(prefix="investor-financial-snapshot-") as temporary:
        snapshot: Path = Path(temporary) / "snapshot.db"
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as source:
            source.execute("PRAGMA query_only = ON")
            with closing(sqlite3.connect(snapshot)) as destination:
                source.backup(destination)
        with closing(sqlite3.connect(snapshot.as_uri() + "?mode=ro", uri=True)) as conn:
            conn.row_factory = sqlite3.Row
            table: str
            for table in CORE_TABLES:
                columns: set[str] = {
                    r["name"] for r in conn.execute(f'PRAGMA table_info("{table}")')
                }
                if columns != SOURCE_COLUMNS[table]:
                    raise ValueError(f"Unsupported legacy {table} columns; review the mapping")
                try:
                    dataset[table] = [
                        normalize(table, row)
                        for row in conn.execute(f'SELECT * FROM "{table}" ORDER BY id')
                    ]
                except (ValueError, TypeError) as exc:
                    raise ValueError(
                        f"Invalid legacy {table} format; source remains unchanged"
                    ) from exc
    sources: dict[str, Row] = {}
    period_companies: dict[int, int] = {
        cast(int, row["id"]): cast(int, row["company_id"]) for row in dataset["company_periods"]
    }
    row: Row
    for row in dataset["metric_values"]:
        reference: Value = row["source_ref"]
        if isinstance(reference, str) and reference.strip():
            period_id: int = cast(int, row["period_id"])
            if period_id not in period_companies:
                raise ValueError("Legacy observation refers to an unknown fiscal period")
            company_id: int = period_companies[period_id]
            row["source_id"] = source_id(company_id, reference)
            sources[str(row["source_id"])] = {
                "id": row["source_id"],
                "company_id": company_id,
                "reference": reference,
                "url": reference if reference.startswith(("https://", "http://")) else None,
            }
    dataset["sources"] = [sources[key] for key in sorted(sources)]
    return dataset


def summary(dataset: Dataset) -> Report:
    """Report counts and a snapshot digest without printing private records."""
    return {
        "counts": {table: len(rows) for table, rows in dataset.items()},
        "snapshot_sha256": hashlib.sha256(json_result(dataset).encode()).hexdigest(),
        "legacy_verification": "legacy_unverified",
    }


def verify(conn: Connection[Row], schema: str, dataset: Dataset) -> Report:
    """Compare every mapped field and refuse any conflicting target data."""
    table: str
    for table in (*CORE_TABLES, "sources"):
        expected: list[Row] = dataset[table]
        actual: list[Row] = conn.execute(
            sql.SQL("SELECT * FROM {} ORDER BY id").format(relation(schema, table))
        ).fetchall()
        if len(actual) != len(expected):
            raise ValueError(f"Target {table} count differs; no overwrite is permitted")
        wanted: Row
        saved: Row
        for wanted, saved in zip(expected, actual, strict=True):
            if any(saved[key] != value for key, value in wanted.items()):
                raise ValueError(f"Target {table} data differs; no overwrite is permitted")
    return {**summary(dataset), "matches": True}


def migrate(conn: Connection[Row], schema: str, dataset: Dataset) -> Report:
    """Import atomically into an empty namespace, or verify an exact rerun."""
    initialize(conn, schema)
    table: str
    for table in (*CORE_TABLES, "sources"):
        if conn.execute(
            sql.SQL("SELECT count(*) AS n FROM {}").format(relation(schema, table))
        ).fetchone()["n"]:
            return {**verify(conn, schema, dataset), "status": "unchanged"}
    record: Row
    for table in ("companies", "metrics", "company_periods", "sources", "metric_values"):
        for record in dataset[table]:
            columns: list[str] = list(record)
            values: list[Value | Jsonb] = [
                Jsonb(value) if key == "categories" and value is not None else value
                for key, value in record.items()
            ]
            conn.execute(
                sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
                    relation(schema, table),
                    sql.SQL(", ").join(map(sql.Identifier, columns)),
                    sql.SQL(", ").join(sql.Placeholder() for _ in columns),
                ),
                values,
            )
    for table in CORE_TABLES:
        conn.execute(
            sql.SQL(
                "SELECT setval(pg_get_serial_sequence(%s, 'id'), COALESCE(MAX(id), 1), "
                "MAX(id) IS NOT NULL) FROM {}"
            ).format(relation(schema, table)),
            (f"{schema}.{table}",),
        )
    return {**verify(conn, schema, dataset), "status": "imported"}
