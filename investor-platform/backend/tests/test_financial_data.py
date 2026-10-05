import json
import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from datetime import date
from decimal import Decimal
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.rows import dict_row
from pydantic import ValidationError

from investor_platform.financial_import import migrate, read_legacy, summary, verify
from investor_platform.financial_store import (
    ObservationBatch,
    append_observations,
    connect,
    grant_access,
    history_rows,
    initialize,
    relation,
)

LEGACY_DDL = """
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
def legacy(tmp_path):
    path = tmp_path / "fixture.db"
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
def financial(database):
    dsn = database.url.render_as_string(hide_password=False).replace(
        "postgresql+psycopg://", "postgresql://"
    )
    schema = "investor_data_test_" + uuid4().hex
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        initialize(conn, schema)
    try:
        yield dsn, schema
    finally:
        with psycopg.connect(dsn) as conn:
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def batch(**extra):
    data = {
        "company_id": 42,
        "period": {
            "period_kind": "year",
            "fiscal_year": 2025,
            "fiscal_label": "FY2025",
            "period_start": "2025-01-01",
            "period_end": "2025-12-31",
        },
        "observations": [
            {
                "metric_key": "revenue.total.reported",
                "value": "123.00000000000000001",
                "currency_code": "USD",
                "source": {
                    "reference": "Synthetic FY2025 report",
                    "url": "https://example.com/fy2025",
                    "published_on": "2026-02-01",
                },
                "source_locator": "Income statement, page 1",
                **extra,
            }
        ],
    }
    return ObservationBatch.model_validate(data)


def test_import_preserves_every_field_missingness_ids_and_source(legacy, financial):
    dsn, schema = financial
    before = summary(read_legacy(legacy))
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        dataset = read_legacy(legacy)
        assert migrate(conn, schema, dataset)["status"] == "imported"
        assert verify(conn, schema, dataset)["matches"]
        assert migrate(conn, schema, dataset)["status"] == "unchanged"
        rows = history_rows(conn, schema, 42)
        assert rows[0]["value"] == Decimal("100.25")
        assert rows[0]["verification_status"] == "legacy_unverified"
        assert rows[0]["published_on"] is None
        assert rows[0]["source_url"] == "https://example.com/report"
        missing = history_rows(conn, schema, 42, scenario="guidance")
        assert missing[0]["value"] is None and missing[0]["value_status"] == "not_disclosed"
        next_id = conn.execute(
            sql.SQL(
                "INSERT INTO {} (name) VALUES ('Another synthetic issuer') RETURNING id"
            ).format(relation(schema, "companies"))
        ).fetchone()["id"]
        assert next_id > 42
    assert summary(read_legacy(legacy)) == before


def test_snapshot_includes_committed_wal_and_does_not_checkpoint(legacy):
    with closing(sqlite3.connect(legacy)) as writer:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("UPDATE metric_values SET value=201.5 WHERE id=99")
        writer.commit()
        assert read_legacy(legacy)["metric_values"][0]["value"] == Decimal("201.5")
        assert writer.execute("SELECT value FROM metric_values WHERE id=99").fetchone()[0] == 201.5


def test_import_conflict_preserves_existing_data(legacy, financial):
    dsn, schema = financial
    original = read_legacy(legacy)
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        migrate(conn, schema, original)
    changed = read_legacy(legacy)
    changed["metric_values"][0]["value"] = Decimal("999")
    with pytest.raises(ValueError, match="no overwrite"):
        with psycopg.connect(dsn, row_factory=dict_row) as conn:
            migrate(conn, schema, changed)
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        assert verify(conn, schema, original)["matches"]


def test_failed_import_rolls_back_all_tables(legacy, financial):
    dsn, schema = financial
    dataset = read_legacy(legacy)
    dataset["metric_values"][0]["metric_id"] = 999
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        with psycopg.connect(dsn, row_factory=dict_row) as conn:
            migrate(conn, schema, dataset)
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        for table in dataset:
            assert (
                conn.execute(
                    sql.SQL("SELECT count(*) AS n FROM {}").format(relation(schema, table))
                ).fetchone()["n"]
                == 0
            )


def test_append_exact_decimals_retry_and_conflict(legacy, financial):
    dsn, schema = financial
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        migrate(conn, schema, read_legacy(legacy))
        assert append_observations(conn, schema, batch()) == {"inserted": 1, "unchanged": 0}
        assert append_observations(conn, schema, batch()) == {"inserted": 0, "unchanged": 1}
        rows = history_rows(conn, schema, 42)
        assert rows[-1]["value"] == Decimal("123.00000000000000001")
        assert rows[-1]["verification_status"] == "unverified"
    with pytest.raises(ValueError, match="conflicts"):
        with psycopg.connect(dsn, row_factory=dict_row) as conn:
            append_observations(conn, schema, batch(value="124"))
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        assert history_rows(conn, schema, 42)[-1]["value"] == Decimal("123.00000000000000001")


def test_append_failure_is_atomic(legacy, financial):
    dsn, schema = financial
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        migrate(conn, schema, read_legacy(legacy))
    data = batch()
    data.observations.append(data.observations[0].model_copy(update={"metric_key": "missing"}))
    with pytest.raises(ValueError, match="Define the metric"):
        with psycopg.connect(dsn, row_factory=dict_row) as conn:
            append_observations(conn, schema, data)
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        assert len(history_rows(conn, schema, 42)) == 1
        assert (
            conn.execute(
                sql.SQL("SELECT count(*) AS n FROM {}").format(relation(schema, "company_periods"))
            ).fetchone()["n"]
            == 1
        )


@pytest.mark.parametrize(
    "extra",
    [
        {"value": 0.1},
        {"value": "NaN"},
        {"value": "Infinity"},
        {"source_locator": None},
        {"source_locator": "   "},
        {"origin": "derived", "calculation_note": "   "},
        {"source": {"reference": "Synthetic report", "retrieved_at": "2026-01-01T12:00:00"}},
        {"qualifier": "range", "value_high": "1"},
        {"value": None},
        {"source": None},
    ],
)
def test_ambiguous_or_invalid_input_is_rejected(extra):
    with pytest.raises(ValidationError):
        batch(**extra)


def test_missing_database_config_and_namespace_fail_closed(monkeypatch):
    monkeypatch.delenv("INVESTOR_DATA_DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://example.invalid/other")
    with pytest.raises(ValueError, match="no database fallback"):
        connect()
    for name in ("public", "investor_data; DROP SCHEMA public", "test_other"):
        with pytest.raises(ValueError):
            relation(name, "companies")


def test_dedicated_roles_can_append_but_not_overwrite_or_verify(legacy, financial):
    dsn, schema = financial
    suffix = uuid4().hex
    reader, writer = "investor_data_reader_" + suffix, "investor_data_writer_" + suffix
    try:
        with psycopg.connect(dsn, row_factory=dict_row) as conn:
            migrate(conn, schema, read_legacy(legacy))
            for role in (reader, writer):
                conn.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(role)))
            grant_access(conn, schema, reader, writer)
        with psycopg.connect(dsn, row_factory=dict_row) as conn:
            conn.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(writer)))
            assert append_observations(conn, schema, batch())["inserted"] == 1
        for role, statement in [
            (
                reader,
                sql.SQL("INSERT INTO {} (name) VALUES ('Forbidden')").format(
                    relation(schema, "companies")
                ),
            ),
            (writer, sql.SQL("UPDATE {} SET value=0").format(relation(schema, "metric_values"))),
            (
                writer,
                sql.SQL("INSERT INTO {} (verification_status) VALUES ('source_verified')").format(
                    relation(schema, "metric_values")
                ),
            ),
        ]:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                with psycopg.connect(dsn) as conn:
                    conn.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(role)))
                    conn.execute(statement)
    finally:
        with psycopg.connect(dsn) as conn:
            for role in (reader, writer):
                conn.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role)))
                conn.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))


def test_cli_chronological_exact_json(legacy, financial):
    dsn, schema = financial
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        migrate(conn, schema, read_legacy(legacy))
        append_observations(conn, schema, batch())
    env = os.environ | {"INVESTOR_DATA_DATABASE_URL": dsn}
    result = subprocess.run(
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
        env=env,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    rows = json.loads(result.stdout)
    assert [row["fiscal_year"] for row in rows] == [2024, 2025]
    assert rows[-1]["value"] == "123.00000000000000001"


def test_quarter_and_ytd_same_end_ranges_and_estimates_remain_distinct(legacy, financial):
    dsn, schema = financial
    quarter = batch(value="110", value_high="120", qualifier="range", scenario="estimate")
    quarter.period = quarter.period.model_copy(
        update={
            "period_kind": "quarter",
            "fiscal_quarter": 2,
            "fiscal_label": "Q2 FY2025",
            "period_start": date(2025, 4, 1),
            "period_end": date(2025, 6, 30),
        }
    )
    ytd = batch(value=None, value_status="not_disclosed")
    ytd.period = quarter.period.model_copy(
        update={
            "period_kind": "ytd",
            "fiscal_label": "H1 FY2025",
            "period_start": date(2025, 1, 1),
        }
    )
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        migrate(conn, schema, read_legacy(legacy))
        append_observations(conn, schema, quarter)
        append_observations(conn, schema, ytd)
        estimate = history_rows(conn, schema, 42, scenario="estimate")[0]
        assert estimate["period_kind"] == "quarter"
        assert estimate["value_high"] == 120 and estimate["qualifier"] == "range"
        actual = history_rows(conn, schema, 42)[-1]
        assert actual["period_kind"] == "ytd" and actual["value"] is None


def test_unknown_source_column_and_foreign_namespace_are_not_modified(legacy, financial):
    with closing(sqlite3.connect(legacy)) as conn:
        conn.execute("ALTER TABLE companies ADD COLUMN extra_information TEXT")
        conn.commit()
    with pytest.raises(ValueError, match="review the mapping"):
        read_legacy(legacy)
    dsn, schema = financial
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        conn.execute(
            sql.SQL("COMMENT ON SCHEMA {} IS 'Another application'").format(sql.Identifier(schema))
        )
    with pytest.raises(ValueError, match="already exists"):
        with psycopg.connect(dsn, row_factory=dict_row) as conn:
            initialize(conn, schema)


def test_cli_validation_error_keeps_values_out_of_stderr(legacy, financial, tmp_path):
    dsn, schema = financial
    payload = batch().model_dump(mode="json")
    payload["observations"][0]["value"] = "PRIVATE_TEST_MARKER"
    input_file = tmp_path / "input.json"
    input_file.write_text(json.dumps(payload))
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "investor_platform.financial_cli",
            "--schema",
            schema,
            "append",
            "--input",
            str(input_file),
        ],
        env=os.environ | {"INVESTOR_DATA_DATABASE_URL": dsn},
        text=True,
        capture_output=True,
    )
    assert result.returncode == 1
    assert "PRIVATE_TEST_MARKER" not in result.stderr
    assert json.loads(result.stderr)["fields"] == [["observations", 0, "value"]]
