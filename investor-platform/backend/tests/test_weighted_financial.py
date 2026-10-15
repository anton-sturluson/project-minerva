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
@pytest.mark.parametrize(
    "key",
    ["fcf_margin_after_disclosed_capex", "allocated_fcf_after_disclosed_capex_per_basic_share"],
)
def test_tampered_disclosed_component_proof_cannot_change_weighted_cash(
    field: str,
    key: str,
) -> None:
    """Refuse altered component evidence even when the cached cash-flow value looks plausible."""
    changed: Record = with_disclosed_capex(profile("example:one"), "3000000", "1000000")
    calculation: Record = record(record(changed["calculations"])[key])
    records(calculation["inputs"])[2][field] = "tampered"
    with pytest.raises(ValueError, match="does not match observation inputs"):
        build_weighted_report(snapshot(), [changed])


def test_missing_disclosed_capex_is_not_replaced_by_legacy_ppe_or_zero() -> None:
    """An old PP&E fact cannot fill missing disclosed components or imply zero spending."""
    result: Record = build_weighted_report(snapshot(), [profile("example:one")])
    assert metric(result, "fcf_margin_after_disclosed_capex")["value"] is None
    assert metric(result, "fcf_margin_after_disclosed_capex")["coverage"] == "0"


def per_share_metric(report: Record, key: str = "weighted_company_eps") -> Record:
    """Read a weighted company amount separately from percentage ratios."""
    return record(record(report["weighted_company_per_share"])[key])


def test_weighted_company_per_share_preserves_negative_values_and_source_proof() -> None:
    """Reported EPS and disclosed-capex FCF use explicit weights and retain source inputs."""
    first: Record = with_disclosed_capex(profile("example:one"), "3000000", "1000000")
    second: Record = with_disclosed_capex(profile("example:two"), "20000000", "0")
    record(record(first["facts"])["basic_eps"])["value"] = "2"
    record(record(second["facts"])["basic_eps"])["value"] = "-1"
    result: Record = build_weighted_report(snapshot(), [first, second])
    eps: Record = per_share_metric(result)
    cash: Record = per_share_metric(result, "weighted_company_fcf_per_share")
    assert Decimal(str(eps["value"])) == Decimal("0.8")
    assert Decimal(str(cash["value"])) == Decimal("0.46")
    assert eps["coverage"] == cash["coverage"] == "1"
    assert eps["unit"] == cash["unit"] == "USD_per_company_share"
    contribution: Record = records(eps["contributions"])[0]
    assert record(contribution["observation"])["observation_id"] == "example:one:basic_eps"
    assert contribution["company_value"] == "2"
    cash_inputs: list[Record] = records(
        record(records(cash["contributions"])[0]["calculation"])["inputs"]
    )
    assert any(i.get("component_ref") for i in cash_inputs)
    assert any(i.get("metric_key") == "basic_weighted_average_shares" for i in cash_inputs)
    assert "weighted_company_eps" not in record(result["weighted_ratios"])


def test_weighted_company_amounts_use_independent_coverage_and_no_zero_fallback() -> None:
    """An absent EPS or uncollected capex removes only the affected amount and issuer."""
    first: Record = with_disclosed_capex(profile("example:one"), "3000000", "1000000")
    second: Record = profile("example:two")
    fact: Record = record(record(first["facts"])["basic_eps"])
    fact.update(status="unavailable", reason="Not reported")
    fact.pop("value")
    result: Record = build_weighted_report(snapshot(), [first, second])
    eps: Record = per_share_metric(result)
    cash: Record = per_share_metric(result, "weighted_company_fcf_per_share")
    assert Decimal(str(eps["value"])) == Decimal("0.8") and eps["coverage"] == "0.4"
    assert cash["value"] == "1.1" and cash["coverage"] == "0.6"
    assert records(eps["exclusions"])[0]["reason"] == "Not reported"
    assert records(cash["exclusions"])[0]["issuer_key"] == "example:two"
    assert metric(result)["coverage"] == "1"


@pytest.mark.parametrize("field", ["source_id", "observation_id", "share_basis"])
def test_weighted_eps_requires_reported_source_and_supported_share_basis(field: str) -> None:
    """A missing or unresolved EPS source or share basis cannot enter the weighted result."""
    selected: Record = profile("example:one")
    fact: Record = record(record(selected["facts"])["basic_eps"])
    fact.pop(field)
    result: Record = build_weighted_report(snapshot(), [selected])
    assert per_share_metric(result)["value"] is None
    assert per_share_metric(result)["coverage"] == "0"
    assert records(per_share_metric(result)["exclusions"])[0]["reason"]


def test_invalid_valuation_withholds_weighted_company_amounts() -> None:
    """A missing market value cannot silently reweight the remaining per-share measures."""
    result: Record = build_weighted_report(snapshot(second=None), [profile("example:one")])
    amount: Record
    for amount in (record(v) for v in record(result["weighted_company_per_share"]).values()):
        assert amount["value"] is None and amount["coverage"] is None


def prior_profile(selected: Record, year: int = 2024) -> Record:
    """Copy a synthetic publication to the prior period on the same reviewed split basis."""
    previous: Record = json.loads(json.dumps(selected))
    record(previous["period"]).update(start=f"{year}-01-01", end=f"{year}-12-31", fiscal_year=year)
    previous["bundle_id"] = "synthetic-prior-publication"
    facts: dict[str, Record] = {k: record(v) for k, v in record(previous["facts"]).items()}
    key: str
    fact: Record
    for key, fact in facts.items():
        fact["observation_id"] = f"prior:{key}"
    previous["calculations"] = calculations(
        facts,
        False,
        record(previous["capital_spending"]) if previous.get("capital_spending") else None,
        str(previous["bundle_id"]),
    )
    return previous


def test_prior_company_and_weighted_changes_retain_source_evidence() -> None:
    """A comparable prior cohort produces Decimal changes without altering current measures."""
    from investor_platform.weighted_financial import add_per_share_comparisons

    first: Record = with_disclosed_capex(profile("example:one"), "3000000", "1000000")
    old: Record = prior_profile(first)
    record(record(old["facts"])["basic_eps"])["value"] = "0.40"
    selected: Record = build_weighted_report(snapshot(), [first])
    prior_snapshot: Record = snapshot()
    prior_snapshot["holdings_date"] = "2024-12-31"
    previous: Record = build_weighted_report(prior_snapshot, [old])
    before: str = json.dumps(selected["weighted_ratios"], sort_keys=True)
    add_per_share_comparisons(selected, previous)
    weighted: Record = record(per_share_metric(selected)["comparison"])
    assert weighted["prior_year"] == 2024 and weighted["prior_value"] == "0.40"
    assert weighted["percent_change"] == "1" and weighted["status"] == "calculated"
    company: Record = records(selected["companies"])[0]
    change: Record = record(record(company["per_share_comparisons"])["basic_eps"])
    assert change["percent_change"] == "1"
    assert record(selected["comparison_inputs"])["companies"] == previous["companies"]
    assert json.dumps(selected["weighted_ratios"], sort_keys=True) == before


@pytest.mark.parametrize("baseline", ["0", "-0.5"])
def test_nonpositive_prior_value_is_not_meaningful(baseline: str) -> None:
    """Zero and loss baselines retain the prior amount without a misleading growth rate."""
    from investor_platform.weighted_financial import change_result

    result: Record = change_result("1", baseline, 2024, None)
    assert result["prior_value"] == baseline
    assert result["status"] == "not_meaningful" and result["percent_change"] is None
    assert change_result("-1", "2", 2024, None)["percent_change"] == "-1.5"


@pytest.mark.parametrize("mismatch", ["split", "classes", "coverage", "weight"])
def test_incomparable_growth_retains_prior_figure_without_rate(mismatch: str) -> None:
    """Changed units, contributors or weights cannot appear as weighted annual growth."""
    from investor_platform.weighted_financial import add_per_share_comparisons

    first: Record = profile("example:one")
    second: Record = profile("example:two")
    old: Record = prior_profile(first)
    old_second: Record = prior_profile(second)
    if mismatch in ("split", "classes"):
        basis: Record = record(record(record(old["facts"])["basic_eps"])["share_basis"])
        basis["split_adjusted_through" if mismatch == "split" else "classes"] = (
            "2024-12-31" if mismatch == "split" else ["different_common"]
        )
    prior_snapshot: Record = snapshot(second="300000" if mismatch == "weight" else "400000")
    prior_snapshot["holdings_date"] = "2024-12-31"
    previous: Record = build_weighted_report(
        prior_snapshot, [old] if mismatch == "coverage" else [old, old_second]
    )
    current: Record = build_weighted_report(snapshot(), [first, second])
    add_per_share_comparisons(current, previous)
    comparison: Record = record(per_share_metric(current)["comparison"])
    assert comparison["prior_value"] is not None
    assert comparison["status"] == "unavailable" and comparison["percent_change"] is None


def test_missing_prior_year_does_not_invent_previous_amount() -> None:
    """Uncollected FY2022 remains unavailable when displaying FY2023 comparisons."""
    from investor_platform.weighted_financial import add_per_share_comparisons

    current_snapshot: Record = snapshot()
    current_snapshot["holdings_date"] = "2023-12-31"
    previous_snapshot: Record = snapshot()
    previous_snapshot["holdings_date"] = "2022-12-31"
    current: Record = build_weighted_report(
        current_snapshot, [prior_profile(profile("example:one"), 2023)]
    )
    add_per_share_comparisons(current, build_weighted_report(previous_snapshot, []))
    comparison: Record = record(per_share_metric(current)["comparison"])
    assert comparison["prior_year"] == 2022 and comparison["prior_value"] is None
    assert comparison["status"] == "unavailable"


def test_proportional_values_preserve_comparison_weights_and_prior_survives_missing_current() -> (
    None
):
    """Scaling all values keeps weights fixed; an unavailable current year retains prior facts."""
    from investor_platform.weighted_financial import add_per_share_comparisons

    first: Record = profile("example:one")
    second: Record = profile("example:two")
    current: Record = build_weighted_report(snapshot(), [first, second])
    old_snapshot: Record = snapshot(first="1200000", second="800000")
    old_snapshot["holdings_date"] = "2024-12-31"
    previous: Record = build_weighted_report(
        old_snapshot, [prior_profile(first), prior_profile(second)]
    )
    add_per_share_comparisons(current, previous)
    assert record(per_share_metric(current)["comparison"])["status"] == "calculated"
    absent: Record = build_weighted_report(snapshot(), [])
    add_per_share_comparisons(absent, previous)
    company: Record = records(absent["companies"])[0]
    comparison: Record = record(record(company["per_share_comparisons"])["basic_eps"])
    assert Decimal(str(comparison["prior_value"])) == Decimal("0.8")
    assert comparison["status"] == "unavailable"
