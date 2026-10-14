"""Exercise real financial evidence, revisions and isolated PostgreSQL transactions."""

import hashlib
import json
import subprocess
from collections.abc import Iterator
from copy import deepcopy
from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest
from jsonschema import ValidationError
from psycopg import Connection, connect, sql
from psycopg.errors import ForeignKeyViolation, RaiseException
from psycopg.rows import dict_row
from sqlalchemy import Engine

from investor_platform.financial import (
    Record,
    Row,
    import_bundle,
    record,
    records,
    relation,
    show,
    validate,
)


@pytest.fixture
def candidate(tmp_path: Path) -> tuple[Path, Record]:
    """Attach real synthetic source bytes to the reusable contract example."""
    fixture: Path = Path("tests/fixtures/financial/synthetic-annual-bundle.json")
    bundle: Record = cast(Record, json.loads(fixture.read_text()))
    source_bytes: bytes = b"Synthetic source: annual statements, FY2025, illustrative values."
    (tmp_path / "source.html").write_bytes(source_bytes)
    source: Record = records(bundle["sources"])[0]
    source["content_sha256"] = hashlib.sha256(source_bytes).hexdigest()
    path: Path = tmp_path / "bundle.json"
    path.write_text(json.dumps(bundle))
    return path, validate(path)


@pytest.fixture
def financial(database: Engine) -> Iterator[tuple[Connection[Row], str]]:
    """Use the existing dev database fixture and an additional isolated financial namespace."""
    schema: str = "investor_financial_test_" + uuid4().hex
    conn: Connection[Row] = connect(
        database.url.render_as_string(hide_password=False).replace(
            "postgresql+psycopg", "postgresql"
        ),
        row_factory=dict_row,
    )
    try:
        yield conn, schema
    finally:
        conn.rollback()
        conn.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema)))
        conn.commit()
        conn.close()


def test_source_bytes_and_semantic_validation(candidate: tuple[Path, Record]) -> None:
    """A schema-valid number is insufficient without unchanged original evidence bytes."""
    path: Path
    bundle: Record
    path, bundle = candidate
    (path.parent / "source.html").write_bytes(b"changed")
    with pytest.raises(ValueError, match="Source bytes"):
        validate(path)
    (path.parent / "source.html").write_bytes(
        b"Synthetic source: annual statements, FY2025, illustrative values."
    )
    record(bundle["issuer"])["reporting_currency"] = "EUR"
    path.write_text(json.dumps(bundle))
    with pytest.raises(ValidationError):
        validate(path)
    record(bundle["issuer"])["reporting_currency"] = "USD"
    record(bundle["period"])["start"] = "2025-11-01"
    path.write_text(json.dumps(bundle))
    with pytest.raises(ValueError, match="annual dates"):
        validate(path)


def test_replay_and_exact_decimal_calculations(
    candidate: tuple[Path, Record], financial: tuple[Connection[Row], str]
) -> None:
    """Read exact decimals and pinned inputs without averaging company earnings or EPS."""
    path: Path
    bundle: Record
    path, bundle = candidate
    conn: Connection[Row]
    schema: str
    conn, schema = financial
    record(record(bundle["facts"])["revenue"])["value"] = "100000000.000000000000000001"
    with conn.transaction():
        assert import_bundle(conn, schema, bundle, True)["status"] == "imported"
    with conn.transaction():
        assert import_bundle(conn, schema, bundle, True)["status"] == "unchanged"
        profile: Record = show(conn, schema, "synthetic-example", 2025)
    facts: Record = record(profile["facts"])
    calculations: Record = record(profile["calculations"])
    assert record(facts["revenue"])["value"] == "100000000.000000000000000001"
    assert record(calculations["allocated_cfo_per_basic_share"])["value"] == "1.5"
    assert record(calculations["allocated_fcf_after_ppe_per_basic_share"])["value"] == "1.2"
    assert (
        record(calculations["net_margin"])["value"]
        != record(calculations["net_margin_common"])["value"]
    )
    assert record(calculations["net_margin"])["inputs"]
    assert profile["review_status"] == "reviewed"


def test_restated_publication_and_candidate_selection(
    candidate: tuple[Path, Record], financial: tuple[Connection[Row], str]
) -> None:
    """Keep prior facts while selecting one complete reviewed publication."""
    path: Path
    original: Record
    path, original = candidate
    conn: Connection[Row]
    schema: str
    conn, schema = financial
    revision: Record = deepcopy(original)
    revision["bundle_id"] = str(uuid4())
    record(record(revision["facts"])["revenue"])["value"] = "200000000"
    with conn.transaction():
        import_bundle(conn, schema, original, True)
        import_bundle(conn, schema, revision, False)
        assert show(conn, schema, "synthetic-example", 2025)["bundle_id"] == original["bundle_id"]
    revision["bundle_id"] = str(uuid4())
    with conn.transaction():
        import_bundle(conn, schema, revision, True)
        profile: Record = show(conn, schema, "synthetic-example", 2025)
        assert profile["bundle_id"] == revision["bundle_id"]
        assert record(record(profile["calculations"])["net_margin"])["value"] == "0.045"
        row: Row | None = conn.execute(
            sql.SQL("SELECT count(*) AS n FROM {}").format(relation(schema, "observations"))
        ).fetchone()
        assert row and row["n"] == 42
    with pytest.raises(RaiseException, match="append-only"), conn.transaction():
        conn.execute(sql.SQL("UPDATE {} SET value=0").format(relation(schema, "observations")))


def test_conflicts_and_atomic_rollback(
    candidate: tuple[Path, Record], financial: tuple[Connection[Row], str]
) -> None:
    """Refuse conflicting replay, fiscal metadata, source metadata and dangling evidence."""
    path: Path
    original: Record
    path, original = candidate
    conn: Connection[Row]
    schema: str
    conn, schema = financial
    with conn.transaction():
        import_bundle(conn, schema, original, True)
    changed: Record = deepcopy(original)
    record(record(changed["facts"])["net_income"])["value"] = "1"
    with pytest.raises(ValueError, match="UUID conflicts"), conn.transaction():
        import_bundle(conn, schema, changed, True)
    changed["bundle_id"] = str(uuid4())
    record(changed["period"])["fiscal_label"] = "changed label"
    with pytest.raises(ValueError, match="Fiscal identity"), conn.transaction():
        import_bundle(conn, schema, changed, True)
    changed = deepcopy(original)
    changed["bundle_id"] = str(uuid4())
    records(changed["sources"])[0]["url"] = "https://example.org/changed"
    with pytest.raises(ValueError, match="identity missing"), conn.transaction():
        import_bundle(conn, schema, changed, True)
    changed = deepcopy(original)
    changed["bundle_id"] = str(uuid4())
    changed_source: Record = records(changed["sources"])[0]
    changed_source["published_on"] = "2026-02-02"
    changed_source["retrieved_at"] = "2026-02-03T12:00:00Z"
    with pytest.raises(ValueError, match="publication date conflicts"), conn.transaction():
        import_bundle(conn, schema, changed, True)
    changed = deepcopy(original)
    changed["bundle_id"] = str(uuid4())
    record(record(changed["facts"])["net_income"])["source_id"] = "absent"
    with pytest.raises(ForeignKeyViolation), conn.transaction():
        import_bundle(conn, schema, changed, True)
    with conn.transaction():
        row: Row | None = conn.execute(
            sql.SQL("SELECT count(*) AS n FROM {}").format(relation(schema, "publications"))
        ).fetchone()
        assert row and row["n"] == 1


def test_unknown_schema_is_preserved(
    candidate: tuple[Path, Record], financial: tuple[Connection[Row], str]
) -> None:
    """Do not adopt or overwrite existing unversioned namespaces."""
    path: Path
    bundle: Record
    path, bundle = candidate
    conn: Connection[Row]
    schema: str
    conn, schema = financial
    with conn.transaction():
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    with pytest.raises(ValueError, match="Unknown existing"), conn.transaction():
        import_bundle(conn, schema, bundle, True)
    with pytest.raises(ValueError, match="legacy schemas"), conn.transaction():
        import_bundle(conn, "investor_data", bundle, True)


def test_cli_validation_stdout_is_json(candidate: tuple[Path, Record]) -> None:
    """An actual CLI invocation emits only parseable JSON on successful stdout."""
    path: Path
    bundle: Record
    path, bundle = candidate
    result: subprocess.CompletedProcess[str] = subprocess.run(
        [".venv/bin/investor-financial", "validate", str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(result.stdout)["status"] == "candidate"
    assert result.stderr == ""


def test_missingness_insurer_and_gross_fallback(
    candidate: tuple[Path, Record], financial: tuple[Connection[Row], str]
) -> None:
    """Derive a supported gross subtotal while withholding FCF for missing capex."""
    path: Path
    bundle: Record
    path, bundle = candidate
    conn: Connection[Row]
    schema: str
    conn, schema = financial
    gross: Record = record(record(bundle["facts"])["gross_profit"])
    gross.pop("value")
    gross.update(status="not_disclosed", reason="No reported gross subtotal")
    capex: Record = record(record(bundle["facts"])["cash_capex_ppe"])
    capex.pop("value")
    capex.update(status="not_disclosed", reason="Only combined spending is disclosed")
    with conn.transaction():
        import_bundle(conn, schema, bundle, True)
        profile: Record = show(conn, schema, "synthetic-example", 2025)
    results: Record = record(profile["calculations"])
    assert record(results["gross_margin"])["value"] == "0.4"
    assert record(results["gross_margin"])["formula"] == "(revenue - cost_of_revenue) / revenue"
    assert record(results["fcf_after_ppe"])["status"] == "unavailable"
    assert "value" not in record(results["fcf_after_ppe"])
    bundle["bundle_id"] = str(uuid4())
    record(bundle["issuer"])["business_type"] = "insurer"
    with conn.transaction():
        import_bundle(conn, schema, bundle, True)
        profile = show(conn, schema, "synthetic-example", 2025)
    assert record(record(profile["calculations"])["gross_margin"])["status"] == "unavailable"


def test_dates_source_references_and_absence_evidence(candidate: tuple[Path, Record]) -> None:
    """Reject unresolved evidence and transitions without conflating fiscal labels with dates."""
    path: Path
    bundle: Record
    path, bundle = candidate
    record(bundle["period"])["fiscal_year"] = 2026
    record(bundle["period"])["fiscal_label"] = "FY2026"
    path.write_text(json.dumps(bundle))
    assert record(validate(path)["period"])["fiscal_year"] == 2026
    record(bundle["period"])["start"] = "2025-02-01"
    path.write_text(json.dumps(bundle))
    with pytest.raises(ValueError, match="annual dates"):
        validate(path)
    record(bundle["period"])["start"] = "2025-01-01"
    record(record(bundle["facts"])["net_income"])["source_id"] = "absent"
    path.write_text(json.dumps(bundle))
    with pytest.raises(ValueError, match="Unresolved source"):
        validate(path)
    fact: Record = record(record(bundle["facts"])["net_income"])
    fact.pop("source_id")
    fact.pop("locator")
    fact.pop("value")
    fact.update(status="not_disclosed", reason="Missing")
    path.write_text(json.dumps(bundle))
    with pytest.raises(ValueError, match="absence evidence"):
        validate(path)


def test_same_transaction_revision_order(
    candidate: tuple[Path, Record], financial: tuple[Connection[Row], str]
) -> None:
    """Select the newer import rather than random UUID order within a transaction."""
    path: Path
    bundle: Record
    path, bundle = candidate
    conn: Connection[Row]
    schema: str
    conn, schema = financial
    bundle["bundle_id"] = "ffffffff-ffff-4fff-8fff-ffffffffffff"
    revision: Record = deepcopy(bundle)
    revision["bundle_id"] = "00000000-0000-4000-8000-000000000001"
    record(record(revision["facts"])["revenue"])["value"] = "200000000"
    with conn.transaction():
        import_bundle(conn, schema, bundle, True)
        import_bundle(conn, schema, revision, True)
        assert show(conn, schema, "synthetic-example", 2025)["bundle_id"] == revision["bundle_id"]
