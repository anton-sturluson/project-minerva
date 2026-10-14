"""Check weighting arithmetic, coverage and dated publication provenance."""

import json
from decimal import Decimal
from pathlib import Path

import pytest

from investor_platform.financial import SCHEMA, Record, calculations, record, records
from investor_platform.weighted_financial import build_weighted_report, render_weighted_report


def profile(issuer_key: str, operating_income: str = "12000000") -> Record:
    """Create a source-backed synthetic annual profile with deterministic formulas."""
    bundle: Record = json.loads(
        (Path(__file__).parent / "fixtures/financial/synthetic-annual-bundle.json").read_text()
    )
    issuer: Record = record(bundle["issuer"])
    issuer["issuer_key"] = issuer_key
    facts: dict[str, Record] = {k: record(v) for k, v in record(bundle["facts"]).items()}
    key: str
    fact: Record
    for key, fact in facts.items():
        fact["observation_id"] = f"{issuer_key}:{key}"
    facts["operating_income"]["value"] = operating_income
    bundle.update(review_status="reviewed", calculations=calculations(facts, False))
    return bundle


def snapshot(first: str | None = "600000", second: str | None = "400000") -> Record:
    """Supply explicit synthetic market values without quantities or quote claims."""
    return {
        "synthetic": True,
        "base_currency": "USD",
        "holdings_date": "2025-12-31",
        "source": "synthetic validation fixture; not actual holdings or market quotes",
        "holdings": [
            {"issuer_key": "example:one", "ticker": "ONE", "market_value": first},
            {"issuer_key": "example:two", "ticker": "TWO", "market_value": second},
        ],
    }


def metric(report: Record, key: str = "operating_margin") -> Record:
    """Read a named weighted result without duplicating its calculation."""
    return record(record(report["weighted_ratios"])[key])


def test_market_value_weighting_differs_from_unweighted_mean() -> None:
    """A 60/40 sleeve produces 28%, rather than the unweighted 25%."""
    report: Record = build_weighted_report(
        snapshot(), [profile("example:one", "40000000"), profile("example:two", "10000000")]
    )
    assert Decimal(str(metric(report)["value"])) == Decimal("0.28")
    assert metric(report)["coverage"] == "1"
    contribution: Record = records(metric(report)["contributions"])[0]
    assert contribution["bundle_id"] == records(report["companies"])[0]["profile"]["bundle_id"]
    assert record(contribution["calculation"])["inputs"]
    assert report["market_value_snapshot"] == snapshot()
    assert report["synthetic"] is True
    assert records(report["companies"])[0]["equity_weight"] == "0.6"


def test_missing_metric_uses_covered_value_and_signed_losses() -> None:
    """Missing facts exclude only the metric; negative numerators retain their sign."""
    first: Record = profile("example:one", "-20000000")
    second: Record = profile("example:two")
    record(record(second["facts"])["operating_income"]).update(
        status="unavailable", reason="Not collected"
    )
    record(record(second["facts"])["operating_income"]).pop("value")
    second["calculations"] = calculations(
        {k: record(v) for k, v in record(second["facts"]).items()}, False
    )
    report: Record = build_weighted_report(snapshot(), [first, second])
    assert Decimal(str(metric(report)["value"])) == Decimal("-0.2")
    assert Decimal(str(metric(report)["coverage"])) == Decimal("0.6")
    assert metric(report)["covered_market_value"] == "600000"
    assert metric(report, "gross_margin")["coverage"] == "1"


@pytest.mark.parametrize("value", [None, "0", "-1", "NaN", "1e3", "1,000"])
def test_invalid_market_value_withholds_every_weighted_metric(value: str | None) -> None:
    """Incomplete valuation must not normalize only the remaining priced positions."""
    report: Record = build_weighted_report(snapshot(second=value), [profile("example:one")])
    assert report["valuation_status"] == "unavailable"
    assert all(c["equity_weight"] is None for c in records(report["companies"]))
    result: Record
    for result in (record(v) for v in record(report["weighted_ratios"]).values()):
        assert result["value"] is None
        assert result["coverage"] is None
        assert result["total_selected_equity_value"] is None


def test_empty_holdings_has_no_ratio_or_coverage() -> None:
    """An empty equity sleeve is unavailable rather than a zero ratio."""
    empty: Record = snapshot()
    empty["holdings"] = []
    report: Record = build_weighted_report(empty, [])
    assert metric(report)["status"] == "unavailable"
    assert metric(report)["coverage"] is None


def test_unknown_issuer_value_remains_in_coverage_denominator() -> None:
    """Unknown companies reduce coverage and keep their value in selected equity."""
    report: Record = build_weighted_report(snapshot(), [profile("example:one")])
    assert metric(report)["total_selected_equity_value"] == "1000000"
    assert metric(report)["covered_market_value"] == "600000"
    assert Decimal(str(metric(report)["coverage"])) == Decimal("0.6")
    assert records(metric(report)["exclusions"])[0]["issuer_key"] == "example:two"


def test_calendar_year_uses_period_end_not_fiscal_label_or_current_values() -> None:
    """A fiscal label cannot admit a period ending outside the selected year."""
    old: Record = profile("example:one")
    period: Record = record(old["period"])
    period.update(start="2024-01-01", end="2024-12-31", fiscal_year=2025)
    report: Record = build_weighted_report(snapshot(), [old, profile("example:two")])
    assert Decimal(str(metric(report)["coverage"])) == Decimal("0.4")
    assert "calendar year" in str(records(metric(report)["exclusions"])[0]["reason"])
    valid: Record = profile("example:one")
    record(valid["period"])["fiscal_year"] = 2026
    assert metric(build_weighted_report(snapshot(), [valid]))["coverage"] == "0.6"


def test_candidate_or_mismatched_observation_cannot_supply_ratio() -> None:
    """Coverage requires reviewed facts and matching calculation observation IDs."""
    candidate: Record = profile("example:one")
    candidate["review_status"] = "candidate"
    other: Record = profile("example:two")
    calculation: Record = record(record(other["calculations"])["operating_margin"])
    records(calculation["inputs"])[0]["observation_id"] = "unrelated-observation"
    report: Record = build_weighted_report(snapshot(), [candidate, other])
    assert metric(report)["value"] is None
    assert metric(report)["coverage"] == "0"
    assert metric(report, "gross_margin")["coverage"] == "0.4"


def test_tampered_cached_calculation_cannot_change_weighted_result() -> None:
    """The shared company formulas must reproduce any saved calculated scalar."""
    changed: Record = profile("example:one")
    record(record(changed["calculations"])["operating_margin"])["value"] = "0.99"
    with pytest.raises(ValueError, match="does not match observation inputs"):
        build_weighted_report(snapshot(), [changed])


def test_duplicate_listing_values_combine_under_one_issuer() -> None:
    """Two selected listings of one issuer do not duplicate financial publications."""
    selected: Record = snapshot()
    records(selected["holdings"])[1]["issuer_key"] = "example:one"
    report: Record = build_weighted_report(selected, [profile("example:one")])
    assert len(records(report["companies"])) == 1
    assert metric(report)["covered_market_value"] == "1000000"
    assert metric(report)["coverage"] == "1"


def test_render_preserves_synthetic_label_and_primary_citations() -> None:
    """The display clearly separates synthetic weights from sourced company figures."""
    report: Record = build_weighted_report(snapshot(), [profile("example:one")])
    text: str = render_weighted_report(report)
    assert "SYNTHETIC WEIGHTS" in text
    assert "2025-12-31" in text
    assert "## References" in text
    assert "https://example.org/" in text
    assert "example:one:operating_income" not in text
    assert "annual-market-value-weighting-v1" not in text
    assert "00000000-0000-4000-8000-000000000003" not in text
    assert "SHA-256" not in text
    assert "Financial period: 2025-01-01 through 2025-12-31" in text
    assert "Allocated consolidated CFO per basic share" in text
    assert "Reported common earnings" in text
    assert "Reported consolidated CFO" in text
    assert "USD 100,000,000" in text
    assert "Financial coverage | Sources" in text
    operating_row: str = next(
        line for line in text.splitlines() if line.startswith("| Operating margin")
    )
    assert "https://example.org/" in operating_row


def test_reader_table_explains_missing_inputs_without_altering_json() -> None:
    """Readable reasons accompany missing cash measures; archival provenance stays intact."""
    missing: Record = profile("example:one")
    facts: dict[str, Record] = {k: record(v) for k, v in record(missing["facts"]).items()}
    facts["cash_capex_ppe"].update(
        status="unavailable", reason="Cash equipment and software spending cannot be separated."
    )
    facts["cash_capex_ppe"].pop("value")
    missing["calculations"] = calculations(facts, False)
    report: Record = build_weighted_report(snapshot(), [missing])
    before: str = json.dumps(report, sort_keys=True)
    text: str = render_weighted_report(report)
    assert "| Reported cash PP&E capex | Unavailable | Cash equipment and software" in text
    assert "| FCF after cash PP&E capex | Unavailable | Missing cash PP&E spending" in text
    assert json.dumps(report, sort_keys=True) == before
    assert "example:one:cash_capex_ppe" in before
    assert "annual-market-value-weighting-v1" in before


def test_non_year_end_snapshot_and_multiple_publications_rejected() -> None:
    """Explicit year-end inputs and one coherent publication avoid ambiguous selection."""
    selected: Record = snapshot()
    selected["holdings_date"] = "2026-10-14"
    with pytest.raises(ValueError, match="year-end"):
        build_weighted_report(selected, [])
    with pytest.raises(ValueError, match="one coherent"):
        build_weighted_report(snapshot(), [profile("example:one"), profile("example:one")])


def with_disclosed_capex(selected: Record, equipment: str, technology: str) -> Record:
    """Attach two distinct synthetic source rows and call the authoritative company formulas."""
    source: Record = records(selected["sources"])[0]
    components: Record = {}
    key: str
    value: str
    for key, value in {"equipment": equipment, "technology_investment": technology}.items():
        components[key] = {
            "status": "reported",
            "unit": "USD",
            "entity_scope": "consolidated",
            "measurement_basis": "duration",
            "value": value,
            "source_id": source["source_id"],
            "locator": {"statement": "Cash flow statement", "row": key, "column": "2025"},
        }
    schema: Record = json.loads(SCHEMA.read_text())
    definition: Record = record(record(schema["$defs"])["capital_spending"])
    selected["capital_spending"] = {
        "scope": record(record(definition["properties"])["scope"])["const"],
        "review_note": "Reviewed disjoint synthetic cash rows; no acquisitions.",
        "components": components,
    }
    selected["calculations"] = calculations(
        {key: record(value) for key, value in record(selected["facts"]).items()},
        False,
        record(selected["capital_spending"]),
        str(selected["bundle_id"]),
    )
    return selected


def test_disclosed_capex_weighting_recomputes_pinned_components() -> None:
    """A weighted FCF margin follows reported components and retains their immutable references."""
    first: Record = with_disclosed_capex(profile("example:one"), "3000000", "1000000")
    second: Record = with_disclosed_capex(profile("example:two"), "1000000", "1000000")
    result: Record = build_weighted_report(snapshot(), [first, second])
    cash: Record = metric(result, "fcf_margin_after_disclosed_capex")
    assert cash["value"] == "0.118" and cash["coverage"] == "1"
    contribution: Record = records(cash["contributions"])[0]
    inputs: list[Record] = records(record(contribution["calculation"])["inputs"])
    assert len(inputs) == 4
    assert (
        inputs[2]["component_ref"] == f"{first['bundle_id']}#/capital_spending/components/equipment"
    )
    assert inputs[2]["value"] == "3000000" and inputs[2]["locator"]


@pytest.mark.parametrize("field", ["component_ref", "value", "source_id", "locator"])
def test_tampered_disclosed_component_proof_cannot_change_weighted_cash(field: str) -> None:
    """Refuse altered component evidence even when the cached cash-flow value looks plausible."""
    changed: Record = with_disclosed_capex(profile("example:one"), "3000000", "1000000")
    calculation: Record = record(
        record(changed["calculations"])["fcf_margin_after_disclosed_capex"]
    )
    records(calculation["inputs"])[2][field] = "tampered"
    with pytest.raises(ValueError, match="does not match observation inputs"):
        build_weighted_report(snapshot(), [changed])


def test_missing_disclosed_capex_is_not_replaced_by_legacy_ppe_or_zero() -> None:
    """An old PP&E fact cannot fill missing disclosed components or imply zero spending."""
    result: Record = build_weighted_report(snapshot(), [profile("example:one")])
    assert metric(result, "fcf_margin_after_disclosed_capex")["value"] is None
    assert metric(result, "fcf_margin_after_disclosed_capex")["coverage"] == "0"
