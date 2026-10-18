from datetime import date

import pytest

from harness.ideas.research import Match, validate_match


def match():
    return Match(
        accepted=True,
        reason="",
        fund="Alpha Fund",
        company="Acme",
        period="Q2 2026",
        period_end=date(2026, 6, 30),
        publisher_quote="Alpha Capital",
        fund_quote="Alpha Fund",
        company_quote="Acme pricing power",
        period_quote="Q2 2026",
    )


def test_match_requires_exact_identity_evidence():
    parts = [{"text": "Alpha Capital Alpha Fund Q2 2026 Acme pricing power"}]
    validate_match(match(), parts, date(2026, 9, 30))
    bad = match()
    bad.company_quote = "Acme doubled earnings"
    with pytest.raises(ValueError, match="verbatim"):
        validate_match(bad, parts, date(2026, 9, 30))


def test_rejects_future_stale_and_missing_periods():
    parts = [{"text": "Alpha Capital Alpha Fund Q2 2026 Acme pricing power"}]
    for period_end in [None, date(2027, 6, 30), date(2025, 6, 30)]:
        bad = match()
        bad.period_end = period_end
        with pytest.raises(ValueError):
            validate_match(bad, parts, date(2026, 9, 30))


def test_provider_schema_avoids_unsupported_additional_properties():
    import json

    from harness.ideas.model import provider_schema

    assert "additionalProperties" not in json.dumps(provider_schema(Match))


def test_identity_checks_tolerate_pdf_line_breaks_and_capitals():
    m = match()
    m.fund_quote = "ALPHA\nFUND"
    m.company_quote = "ACME pricing power"
    m.publisher_quote = "ALPHA CAPITAL"
    validate_match(
        m,
        [{"text": "Alpha Capital Alpha Fund Q2 2026 Acme pricing power"}],
        date(2026, 9, 30),
    )


def test_company_and_sibling_fund_cannot_be_substituted():
    from harness.ideas.research import validate_target

    m = match()
    with pytest.raises(ValueError, match="company"):
        validate_target(
            m, {"company": "Samsung", "fund": "Alpha Fund", "symbol": "SSNLF US"}
        )
    with pytest.raises(ValueError, match="fund"):
        validate_target(
            m, {"company": "Acme", "fund": "Alpha Global Fund", "symbol": "ACM US"}
        )
    validate_target(
        m, {"company": "Acme Corporation", "fund": "Alpha Strategy", "symbol": "ACM US"}
    )


def test_normalized_year_cannot_make_an_old_letter_look_current():
    m = match()
    m.period = "Q2 2025"
    m.period_quote = "Q2 2025"
    with pytest.raises(ValueError, match="year conflicts"):
        validate_match(
            m,
            [{"text": "Alpha Capital Alpha Fund Q2 2025 Acme pricing power"}],
            date(2026, 9, 30),
        )


def test_short_issuer_name_requires_full_name_in_the_same_document() -> None:
    """A letter can introduce a full issuer name before using its short name."""
    candidate: Match = match()
    candidate.company = "Inovance"
    candidate.company_quote = "Inovance pricing power"
    row: dict[str, str] = {
        "company": "Shenzhen Inovance",
        "fund": "Alpha Fund",
        "symbol": "300124 CH",
    }
    parts: list[dict[str, str]] = [
        {"text": "Alpha Capital Alpha Fund Q2 2026 initiated Shenzhen Inovance."},
        {"text": "Inovance pricing power"},
    ]
    validate_match(candidate, parts, date(2026, 9, 30), row)
    with pytest.raises(ValueError, match="company does not match"):
        validate_match(candidate, parts[1:], date(2026, 9, 30), row)


@pytest.mark.parametrize("observed", ["Vance", "Shenzhen", "Other Inovance"])
def test_issuer_alias_does_not_allow_substrings_or_other_issuers(observed: str) -> None:
    """Full-name evidence cannot authorize a partial word or a different issuer."""
    candidate: Match = match()
    candidate.company = observed
    candidate.company_quote = observed + " pricing power"
    row: dict[str, str] = {"company": "Shenzhen Inovance", "fund": "Alpha Fund"}
    parts: list[dict[str, str]] = [
        {
            "text": "Alpha Capital Alpha Fund Q2 2026 Shenzhen Inovance. "
            + candidate.company_quote
        }
    ]
    with pytest.raises(ValueError, match="company does not match"):
        validate_match(candidate, parts, date(2026, 9, 30), row)


def test_issuer_alias_cannot_assemble_full_name_from_unrelated_blocks() -> None:
    """Two adjacent source blocks are not evidence of one complete issuer name."""
    candidate: Match = match()
    candidate.company = "Inovance"
    candidate.company_quote = "Inovance pricing power"
    row: dict[str, str] = {"company": "Shenzhen Inovance", "fund": "Alpha Fund"}
    parts: list[dict[str, str]] = [
        {"text": "Alpha Capital Alpha Fund Q2 2026 Shenzhen"},
        {"text": "Inovance pricing power"},
    ]
    with pytest.raises(ValueError, match="company does not match"):
        validate_match(candidate, parts, date(2026, 9, 30), row)


def test_issuer_alias_does_not_relax_sibling_fund_matching() -> None:
    """Evidence for an issuer alias cannot substitute a different fund."""
    candidate: Match = match()
    candidate.company = "Inovance"
    candidate.company_quote = "Inovance pricing power"
    row: dict[str, str] = {"company": "Shenzhen Inovance", "fund": "Alpha Global Fund"}
    parts: list[dict[str, str]] = [
        {"text": "Alpha Capital Alpha Fund Q2 2026 Shenzhen Inovance."},
        {"text": "Inovance pricing power"},
    ]
    with pytest.raises(ValueError, match="fund does not match"):
        validate_match(candidate, parts, date(2026, 9, 30), row)
