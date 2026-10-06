"""Exercise financial migration and read access with synthetic SQLite and PostgreSQL data."""

import json
import os
import sqlite3
import subprocess
import sys
from collections.abc import Iterator
from contextlib import closing
from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg import Connection, sql
from psycopg.rows import dict_row
from sqlalchemy import Connection as SQLConnection
from sqlalchemy import Engine, text

from investor_platform.financial_import import migrate, read_legacy, summary, verify
from investor_platform.financial_store import (
    Dataset,
    Row,
    company_rows,
    grant_reader,
    history_rows,
    initialize,
    relation,
)

LEGACY_DDL: str = """
CREATE TABLE companies (id INTEGER PRIMARY KEY, ticker TEXT, name TEXT, sector TEXT,
 created_at TEXT, updated_at TEXT, description TEXT, categories TEXT,
 folder_exists INTEGER, exchange TEXT);
CREATE TABLE metrics (id INTEGER PRIMARY KEY, metric_key TEXT, display_name TEXT,
 description TEXT, value_type TEXT, created_at TEXT, updated_at TEXT);
CREATE TABLE company_periods (id INTEGER PRIMARY KEY, company_id INTEGER, period_kind TEXT,
 fiscal_year INTEGER, fiscal_quarter INTEGER, fiscal_label TEXT, period_start TEXT,
 period_end TEXT, created_at TEXT, updated_at TEXT);
CREATE TABLE metric_values (id INTEGER PRIMARY KEY, metric_id INTEGER, period_id INTEGER,
 value REAL, value_high REAL, value_status TEXT, qualifier TEXT, scenario TEXT, origin TEXT,
 currency_code TEXT, reported_text TEXT, source_ref TEXT, calculation_note TEXT,
 created_at TEXT, updated_at TEXT);
"""


@pytest.fixture
def legacy(tmp_path: Path) -> Path:
    """Create synthetic legacy records, including an explicitly missing observation."""
    path: Path = tmp_path / "fixture.db"
    conn: sqlite3.Connection
    with closing(sqlite3.connect(path)) as conn:
        conn.executescript(LEGACY_DDL)
        conn.execute(
            "INSERT INTO companies VALUES "
            "(42,'DEMO','Synthetic issuer',NULL,'2026-01-01','2026-01-01',"
            "'Fixture','[\"Software\"]',1,'TEST')"
        )
        conn.execute(
            "INSERT INTO metrics VALUES "
            "(17,'revenue.total.reported','Revenue','Consolidated revenue','currency',"
            "'2026-01-01','2026-01-01')"
        )
        conn.execute(
            "INSERT INTO company_periods VALUES "
            "(23,42,'year',2024,NULL,'FY2024','2024-01-01','2024-12-31',"
            "'2026-01-01','2026-01-01')"
        )
        conn.execute(
            "INSERT INTO metric_values VALUES "
            "(99,17,23,100.25,NULL,'valid','exact','actual','reported','USD',"
            "'$100.25','https://example.com/report',NULL,'2026-01-01','2026-01-01')"
        )
        conn.execute(
            "INSERT INTO metric_values VALUES "
            "(100,17,23,NULL,NULL,'not_disclosed','exact','guidance','reported',NULL,"
            "NULL,'https://example.com/report',NULL,'2026-01-01','2026-01-01')"
        )
        conn.commit()
    return path


@pytest.fixture
def financial(database: Engine) -> Iterator[tuple[str, str]]:
    """Isolate each PostgreSQL test from real portfolio and financial records."""
    dsn: str = database.url.render_as_string(hide_password=False).replace(
        "postgresql+psycopg://", "postgresql://"
    )
    schema: str = "investor_data_test_" + uuid4().hex
    conn: Connection[Row]
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        initialize(conn, schema)
    try:
        yield dsn, schema
    finally:
        with psycopg.connect(dsn, row_factory=dict_row) as conn:
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def test_import_fidelity_missingness_sequences_and_retry(
    legacy: Path, financial: tuple[str, str]
) -> None:
    """Preserve every mapped field, missing figures and identities across exact retries."""
    dsn: str
    schema: str
    conn: Connection[Row]
    dsn, schema = financial
    dataset: Dataset = read_legacy(legacy)
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        assert migrate(conn, schema, dataset)["status"] == "imported"
        assert verify(conn, schema, dataset)["matches"]
        assert migrate(conn, schema, dataset)["status"] == "unchanged"
        row: Row = history_rows(conn, schema, 42)[0]
        assert row["value"] == Decimal("100.25")
        assert row["verification_status"] == "legacy_unverified" and row["published_on"] is None
        assert row["source_url"] == "https://example.com/report"
        missing: Row = history_rows(conn, schema, 42, scenario="guidance")[0]
        assert missing["value"] is None and missing["value_status"] == "not_disclosed"
        assert (
            conn.execute(
                sql.SQL(
                    "INSERT INTO {} (name) VALUES ('Synthetic second issuer') RETURNING id"
                ).format(relation(schema, "companies"))
            ).fetchone()["id"]
            > 42
        )
    assert summary(read_legacy(legacy)) == summary(dataset)


def test_committed_wal_is_included(legacy: Path) -> None:
    """Read committed WAL records while the writer remains open."""
    writer: sqlite3.Connection
    with closing(sqlite3.connect(legacy)) as writer:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("UPDATE metric_values SET value=201.5 WHERE id=99")
        writer.commit()
        assert read_legacy(legacy)["metric_values"][0]["value"] == Decimal("201.5")


def test_conflicting_retry_preserves_target(legacy: Path, financial: tuple[str, str]) -> None:
    """Refuse a changed source snapshot without overwriting the prepared copy."""
    dsn: str
    schema: str
    conn: Connection[Row]
    dsn, schema = financial
    dataset: Dataset = read_legacy(legacy)
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        migrate(conn, schema, dataset)
    changed: Dataset = read_legacy(legacy)
    changed["metric_values"][0]["value"] = Decimal("999")
    with pytest.raises(ValueError, match="no overwrite"):
        with psycopg.connect(dsn, row_factory=dict_row) as conn:
            migrate(conn, schema, changed)
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        assert verify(conn, schema, dataset)["matches"]


def test_foreign_key_failure_rolls_back_import(legacy: Path, financial: tuple[str, str]) -> None:
    """Reject broken references without retaining a partial import."""
    dsn: str
    schema: str
    conn: Connection[Row]
    dsn, schema = financial
    dataset: Dataset = read_legacy(legacy)
    dataset["metric_values"][0]["metric_id"] = 999
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        with psycopg.connect(dsn, row_factory=dict_row) as conn:
            migrate(conn, schema, dataset)
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        table: str
        for table in dataset:
            assert (
                conn.execute(
                    sql.SQL("SELECT count(*) AS n FROM {}").format(relation(schema, table))
                ).fetchone()["n"]
                == 0
            )


def test_unknown_columns_and_schema_versions_are_refused(
    legacy: Path, financial: tuple[str, str]
) -> None:
    """Prevent silent source-field loss and changes to unsupported target schemas."""
    source: sqlite3.Connection
    with closing(sqlite3.connect(legacy)) as source:
        source.execute("ALTER TABLE companies ADD COLUMN extra_information TEXT")
        source.commit()
    with pytest.raises(ValueError, match="review the mapping"):
        read_legacy(legacy)
    dsn: str
    schema: str
    conn: Connection[Row]
    dsn, schema = financial
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        conn.execute(
            sql.SQL("COMMENT ON SCHEMA {} IS 'minerva-financial-inputs-v1'").format(
                sql.Identifier(schema)
            )
        )
    with pytest.raises(ValueError, match="already exists"):
        with psycopg.connect(dsn, row_factory=dict_row) as conn:
            initialize(conn, schema)
    with pytest.raises(ValueError):
        relation("public", "companies")


def test_issuer_source_and_period_identity(legacy: Path, financial: tuple[str, str]) -> None:
    """Keep duplicate tickers, document labels and fiscal labels separate by real identity."""
    source: sqlite3.Connection
    with closing(sqlite3.connect(legacy)) as source:
        source.execute("UPDATE metric_values SET source_ref='FY2024 annual report'")
        source.execute(
            "INSERT INTO companies SELECT 43,ticker,'Another synthetic "
            "issuer',sector,created_at,updated_at,description,categories,folder_exists,'OTHER' "
            "FROM companies WHERE id=42"
        )
        source.execute(
            "INSERT INTO company_periods SELECT "
            "24,43,period_kind,fiscal_year,fiscal_quarter,fiscal_label,"
            "period_start,period_end,created_at,updated_at "
            "FROM company_periods WHERE id=23"
        )
        source.execute(
            "INSERT INTO company_periods SELECT "
            "25,42,period_kind,fiscal_year,fiscal_quarter,fiscal_label,"
            "'2024-07-01',period_end,created_at,updated_at "
            "FROM company_periods WHERE id=23"
        )
        source.execute(
            "INSERT INTO metric_values SELECT "
            "101,metric_id,24,value,value_high,value_status,qualifier,scenario,origin,"
            "currency_code,reported_text,source_ref,calculation_note,created_at,updated_at "
            "FROM metric_values WHERE id=99"
        )
        source.commit()
    dsn: str
    schema: str
    conn: Connection[Row]
    dsn, schema = financial
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        migrate(conn, schema, read_legacy(legacy))
        assert len(company_rows(conn, schema, "DEMO")) == 2
        assert (
            history_rows(conn, schema, 42)[0]["source_id"]
            != history_rows(conn, schema, 43)[0]["source_id"]
        )
        assert (
            conn.execute(
                sql.SQL("SELECT count(*) AS n FROM {}").format(relation(schema, "company_periods"))
            ).fetchone()["n"]
            == 3
        )


def test_reader_permissions_and_cli_json(
    legacy: Path, financial: tuple[str, str], database: Engine
) -> None:
    """Check reader permissions and read-only CLI decimal JSON, ordering and limits."""
    dsn: str
    schema: str
    conn: Connection[Row]
    dsn, schema = financial
    portfolio_conn: SQLConnection
    with database.connect() as portfolio_conn:
        portfolio_schema: str = str(
            portfolio_conn.execute(text("SELECT current_schema()")).scalar_one()
        )
    reader: str = "investor_data_reader_" + uuid4().hex
    try:
        dataset: Dataset = read_legacy(legacy)
        dataset["company_periods"].append(
            {
                **dataset["company_periods"][0],
                "id": 24,
                "fiscal_year": 2025,
                "fiscal_label": "FY2025",
                "period_start": date(2025, 1, 1),
                "period_end": date(2025, 12, 31),
            }
        )
        dataset["metric_values"].append(
            {
                **dataset["metric_values"][0],
                "id": 101,
                "period_id": 24,
                "value": Decimal("0.1"),
                "reported_text": "$0.10",
            }
        )
        with psycopg.connect(dsn, row_factory=dict_row) as conn:
            migrate(conn, schema, dataset)
            conn.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(reader)))
            grant_reader(conn, schema, reader)
        with psycopg.connect(dsn, row_factory=dict_row) as conn:
            conn.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(reader)))
            assert history_rows(conn, schema, 42)[0]["value"] == Decimal("100.25")
        statement: sql.Composed
        for statement in [
            sql.SQL("INSERT INTO {} (name) VALUES ('Forbidden')").format(
                relation(schema, "companies")
            ),
            sql.SQL("UPDATE {} SET value=0").format(relation(schema, "metric_values")),
            sql.SQL("SELECT * FROM {}").format(sql.Identifier(portfolio_schema, "ledger_entries")),
        ]:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                with psycopg.connect(dsn, row_factory=dict_row) as conn:
                    conn.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(reader)))
                    conn.execute(statement)
        result: subprocess.CompletedProcess[str] = subprocess.run(
            [
                sys.executable,
                "-m",
                "investor_platform.financial_cli",
                "--schema",
                schema,
                "history",
                "--company-id",
                "42",
            ],
            env=os.environ | {"INVESTOR_DATA_DATABASE_URL": dsn},
            text=True,
            capture_output=True,
        )
        assert result.returncode == 0, result.stderr
        rows: list[dict[str, str]] = json.loads(result.stdout)
        assert [row["fiscal_label"] for row in rows] == ["FY2024", "FY2025"]
        assert [row["value"] for row in rows] == ["100.25", "0.1"]
        with psycopg.connect(dsn, row_factory=dict_row) as conn:
            assert history_rows(conn, schema, 42, limit=1)[0]["fiscal_year"] == 2025
    finally:
        with psycopg.connect(dsn, row_factory=dict_row) as conn:
            conn.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(reader)))
            conn.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(reader)))
