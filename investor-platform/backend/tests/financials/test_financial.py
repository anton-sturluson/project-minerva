"""Exercise real financial evidence, revisions and isolated PostgreSQL transactions."""

import hashlib
import json
import subprocess
import sys
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

from investor_platform.financials.bundles import SCHEMA, validate
from investor_platform.financials.calculations import calculations
from investor_platform.financials.storage import import_bundle, relation, show
from investor_platform.financials.types import Json, Record, Row, record, records


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
        [sys.executable, "-m", "investor_platform.financials.cli", "validate", str(path)],
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
    insurer_gross: Record = record(record(profile["calculations"])["gross_margin"])
    assert insurer_gross["status"] == "unavailable"
    assert "not applicable" in str(insurer_gross["reason"])


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


def add_capital_spending(bundle: Record, values: dict[str, str]) -> None:
    """Attach disjoint synthetic reported cash rows using the canonical fixed scope."""
    source: Record = records(bundle["sources"])[0]
    components: Record = {}
    key: str
    value: str
    for key, value in values.items():
        components[key] = {
            "status": "reported",
            "unit": "USD",
            "entity_scope": "consolidated",
            "measurement_basis": "duration",
            "value": value,
            "source_id": source["source_id"],
            "locator": {
                "statement": "Consolidated Statements of Cash Flows",
                "row": key,
                "column": "2025",
            },
        }
    schema: Record = json.loads(SCHEMA.read_text())
    definition: Record = record(record(schema["$defs"])["capital_spending"])
    scope: Json = record(record(definition["properties"])["scope"])["const"]
    bundle["capital_spending"] = {
        "scope": scope,
        "review_note": "Reviewed disjoint annual cash investment rows; no acquisitions.",
        "components": components,
    }


def test_disclosed_capital_spending_sum_is_persisted_and_reproducible(
    candidate: tuple[Path, Record], financial: tuple[Connection[Row], str]
) -> None:
    """A source-backed component sum restores FCF without changing archival PP&E facts."""
    path: Path
    bundle: Record
    path, bundle = candidate
    add_capital_spending(
        bundle,
        {
            "equipment": "8000",
            "leasehold_improvements": "4000",
            "technology_investment": "20000",
            "patents": "1000",
        },
    )
    path.write_text(json.dumps(bundle))
    validate(path)
    conn: Connection[Row]
    schema: str
    conn, schema = financial
    with conn.transaction():
        import_bundle(conn, schema, bundle, True)
        result: Record = show(conn, schema, "synthetic-example", 2025)
    assert result["capital_spending"] == bundle["capital_spending"]
    cash: Record = record(record(result["calculations"])["fcf_after_disclosed_capex"])
    assert cash["capital_spending_total"] == "33000" and cash["value"] == "14967000"
    assert cash["scope"] == record(bundle["capital_spending"])["scope"]
    assert len(records(cash["inputs"])) == 5
    component: Record = records(cash["inputs"])[1]
    assert (
        component["component_ref"]
        == f"{bundle['bundle_id']}#/capital_spending/components/equipment"
    )
    assert component["locator"] and component["source_id"] and component["value"] == "8000"
    assert record(record(result["calculations"])["fcf_after_ppe"])["value"] == "12000000"


@pytest.mark.parametrize(
    "problem", ["overlap", "duplicate_locator", "missing", "source", "negative"]
)
def test_invalid_capital_spending_is_refused(candidate: tuple[Path, Record], problem: str) -> None:
    """Reject unsupported sums rather than presenting source gaps as zero capital spending."""
    path: Path
    bundle: Record
    path, bundle = candidate
    add_capital_spending(bundle, {"equipment": "8000", "technology_investment": "20000"})
    spending: Record = record(bundle["capital_spending"])
    components: Record = record(spending["components"])
    fact: Record = record(components["equipment"])
    if problem == "overlap":
        components["ppe"] = deepcopy(fact)
    elif problem == "duplicate_locator":
        record(components["technology_investment"])["locator"] = deepcopy(fact["locator"])
    elif problem == "missing":
        fact.pop("value")
        fact.update(status="not_disclosed", reason="Missing")
    elif problem == "source":
        fact["source_id"] = "absent"
    else:
        fact["value"] = "-1"
    path.write_text(json.dumps(bundle))
    with pytest.raises((ValueError, ValidationError)):
        validate(path)


def test_component_duplicate_keys_and_v1_namespace_are_refused(
    candidate: tuple[Path, Record], financial: tuple[Connection[Row], str]
) -> None:
    """Do not lose repeated source keys or automatically migrate an old financial namespace."""
    path: Path
    bundle: Record
    path, bundle = candidate
    text: str = json.dumps(bundle).replace(
        '"schema_version": "1.0"', '"schema_version": "1.0", "schema_version": "1.0"'
    )
    path.write_text(text)
    with pytest.raises(ValueError, match="Duplicate JSON key"):
        validate(path)
    conn: Connection[Row]
    schema: str
    conn, schema = financial
    with conn.transaction():
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        conn.execute(
            sql.SQL("COMMENT ON SCHEMA {} IS 'annual-financial-v1'").format(sql.Identifier(schema))
        )
    with pytest.raises(ValueError, match="Unknown existing"), conn.transaction():
        import_bundle(conn, schema, bundle, True)


def test_disclosed_fcf_per_share_uses_annual_basic_shares_and_keeps_sources(
    candidate: tuple[Path, Record], financial: tuple[Connection[Row], str]
) -> None:
    """Divide source-backed FCF by annual basic shares rather than the year-end share snapshot."""
    path: Path
    bundle: Record
    path, bundle = candidate
    add_capital_spending(bundle, {"equipment": "8000", "technology_investment": "20000"})
    conn: Connection[Row]
    schema: str
    conn, schema = financial
    with conn.transaction():
        import_bundle(conn, schema, bundle, True)
        result: Record = show(conn, schema, "synthetic-example", 2025)
    facts: Record = record(result["facts"])
    cash: Record = record(
        record(result["calculations"])["allocated_fcf_after_disclosed_capex_per_basic_share"]
    )
    assert cash["value"] == "1.4972"
    denominator: Record = records(cash["inputs"])[1]
    assert denominator["metric_key"] == "basic_weighted_average_shares"
    assert (
        denominator["observation_id"]
        == record(facts["basic_weighted_average_shares"])["observation_id"]
    )
    assert denominator["value"] == "10000000"
    assert denominator["value"] != record(facts["period_end_common_shares"])["value"]
    assert denominator["source_id"] and denominator["locator"]
    assert denominator["share_basis"] == cash["share_basis"]
    assert len(records(cash["inputs"])) == 4
    assert records(cash["inputs"])[2]["component_ref"]
    assert cash["scope"] == record(bundle["capital_spending"])["scope"]


@pytest.mark.parametrize("problem", ["missing", "zero", "negative", "basis", "class_equivalence"])
def test_disclosed_fcf_per_share_withholds_unsupported_denominators(
    candidate: tuple[Path, Record], problem: str
) -> None:
    """Missing shares and unreviewed share-class bases cannot become valid per-share amounts."""
    path: Path
    bundle: Record
    path, bundle = candidate
    add_capital_spending(bundle, {"equipment": "8000"})
    facts: dict[str, Record] = {
        key: record(value) for key, value in record(bundle["facts"]).items()
    }
    key: str
    fact: Record
    for key, fact in facts.items():
        fact["observation_id"] = key
    shares: Record = facts["basic_weighted_average_shares"]
    if problem == "missing":
        shares.update(status="unavailable", reason="Not reported")
        shares.pop("value")
    elif problem in {"zero", "negative"}:
        shares["value"] = "0" if problem == "zero" else "-1"
    elif problem == "basis":
        shares.pop("share_basis")
    else:
        record(shares["share_basis"])["classes"] = ["Class A", "Class B"]
    results: Record = calculations(
        facts, False, record(bundle["capital_spending"]), str(bundle["bundle_id"])
    )
    cash: Record = record(results["allocated_fcf_after_disclosed_capex_per_basic_share"])
    assert cash["status"] == "unavailable" and "value" not in cash
    assert "revenue" not in str(cash["reason"])


def test_disclosed_fcf_per_share_keeps_signed_loss_and_reviewed_class_basis(
    candidate: tuple[Path, Record],
) -> None:
    """An accepted common-class basis permits a signed per-share cash-flow loss."""
    path: Path
    bundle: Record
    path, bundle = candidate
    add_capital_spending(bundle, {"equipment": "8000"})
    facts: dict[str, Record] = {
        key: record(value) for key, value in record(bundle["facts"]).items()
    }
    key: str
    fact: Record
    for key, fact in facts.items():
        fact["observation_id"] = key
    facts["operating_cash_flow"]["value"] = "-2000"
    basis: Record = record(facts["basic_weighted_average_shares"]["share_basis"])
    basis.update(classes=["Class A", "Class B"], equivalence_note="Same economic rights")
    results: Record = calculations(
        facts, False, record(bundle["capital_spending"]), str(bundle["bundle_id"])
    )
    cash: Record = record(results["allocated_fcf_after_disclosed_capex_per_basic_share"])
    assert cash["value"] == "-0.001" and cash["share_basis"] == basis
