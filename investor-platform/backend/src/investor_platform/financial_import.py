"""Read a WAL-consistent SQLite snapshot and copy only financial input tables."""

import hashlib
import json
import math
import sqlite3
from contextlib import closing
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

from psycopg import sql
from psycopg.types.json import Jsonb

from .financial_store import CORE_TABLES, initialize, json_result, relation, source_id

DATE_FIELDS = {"period_start", "period_end"}
TIME_FIELDS = {"created_at", "updated_at"}
SOURCE_COLUMNS = {
    "companies": {
        "id",
        "ticker",
        "name",
        "sector",
        "description",
        "categories",
        "folder_exists",
        "exchange",
        "created_at",
        "updated_at",
    },
    "metrics": {
        "id",
        "metric_key",
        "display_name",
        "description",
        "value_type",
        "created_at",
        "updated_at",
    },
    "company_periods": {
        "id",
        "company_id",
        "period_kind",
        "fiscal_year",
        "fiscal_quarter",
        "fiscal_label",
        "period_start",
        "period_end",
        "created_at",
        "updated_at",
    },
    "metric_values": {
        "id",
        "metric_id",
        "period_id",
        "value",
        "value_high",
        "value_status",
        "qualifier",
        "scenario",
        "origin",
        "currency_code",
        "reported_text",
        "source_ref",
        "calculation_note",
        "created_at",
        "updated_at",
    },
}


def normalize(table, row):
    result = dict(row)
    for key, value in result.items():
        if value is None:
            continue
        if key in DATE_FIELDS:
            result[key] = date.fromisoformat(value)
        elif key in TIME_FIELDS:
            stamp = datetime.fromisoformat(value)
            result[key] = stamp.replace(tzinfo=UTC) if stamp.tzinfo is None else stamp
        elif key in {"value", "value_high"}:
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError("Legacy observations must be finite")
            result[key] = Decimal(str(value))
    if table == "companies":
        if result.get("categories") is not None:
            categories = json.loads(result["categories"])
            if not isinstance(categories, list) or not all(isinstance(x, str) for x in categories):
                raise ValueError("Legacy company categories must be a JSON array of strings")
            result["categories"] = categories
        if result.get("folder_exists") not in {0, 1}:
            raise ValueError("Legacy folder flag must be zero or one")
        result["folder_exists"] = bool(result["folder_exists"])
    if table == "metric_values":
        reference = result.get("source_ref")
        result["source_id"] = source_id(reference) if reference and reference.strip() else None
        result["verification_status"] = "legacy_unverified"
    return result


def read_legacy(path):
    path = Path(path).resolve(strict=True)
    dataset = {}
    # mode=ro includes committed WAL data; immutable=1 would incorrectly ignore it.
    with TemporaryDirectory(prefix="investor-financial-snapshot-") as temporary:
        snapshot = Path(temporary) / "snapshot.db"
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as source:
            source.execute("PRAGMA query_only = ON")
            with closing(sqlite3.connect(snapshot)) as destination:
                source.backup(destination)
        with closing(sqlite3.connect(snapshot.as_uri() + "?mode=ro", uri=True)) as conn:
            conn.row_factory = sqlite3.Row
            for table in CORE_TABLES:
                columns = {r["name"] for r in conn.execute(f'PRAGMA table_info("{table}")')}
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
    sources = {}
    for row in dataset["metric_values"]:
        if row["source_id"] is not None:
            reference = row["source_ref"]
            sources[row["source_id"]] = {
                "id": row["source_id"],
                "reference": reference,
                "url": reference if reference.startswith(("https://", "http://")) else None,
            }
    dataset["sources"] = sorted(sources.values(), key=lambda row: str(row["id"]))
    return dataset


def summary(dataset):
    serialized = json_result(dataset).encode()
    return {
        "counts": {table: len(rows) for table, rows in dataset.items()},
        "snapshot_sha256": hashlib.sha256(serialized).hexdigest(),
        "legacy_verification": "legacy_unverified",
    }


def verify(conn, schema, dataset):
    """Compare every migrated field, not only counts or selected examples."""
    for table in (*CORE_TABLES, "sources"):
        expected = dataset[table]
        actual = conn.execute(
            sql.SQL("SELECT * FROM {} ORDER BY id").format(relation(schema, table))
        ).fetchall()
        if len(actual) != len(expected):
            raise ValueError(f"Target {table} count differs; no overwrite is permitted")
        if table == "sources":
            actual.sort(key=lambda row: str(row["id"]))
        for wanted, saved in zip(expected, actual, strict=True):
            if any(saved[key] != value for key, value in wanted.items()):
                raise ValueError(f"Target {table} data differs; no overwrite is permitted")
    return {**summary(dataset), "matches": True}


def migrate(conn, schema, dataset):
    initialize(conn, schema)
    counts = [
        conn.execute(
            sql.SQL("SELECT count(*) AS n FROM {}").format(relation(schema, table))
        ).fetchone()["n"]
        for table in (*CORE_TABLES, "sources")
    ]
    if any(counts):
        return {**verify(conn, schema, dataset), "status": "unchanged"}
    for table in ("companies", "metrics", "company_periods", "sources", "metric_values"):
        for record in dataset[table]:
            columns = list(record)
            values = [
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
                "SELECT setval(pg_get_serial_sequence(%s, 'id'), "
                "COALESCE(MAX(id), 1), MAX(id) IS NOT NULL) FROM {}"
            ).format(relation(schema, table)),
            (f"{schema}.{table}",),
        )
    return {**verify(conn, schema, dataset), "status": "imported"}
