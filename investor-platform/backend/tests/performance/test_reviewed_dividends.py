"""Final issuer evidence corrects comparison inputs without changing recorded cash."""

from copy import deepcopy
from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from investor_platform.market_data.types import History
from investor_platform.models import LedgerEntry, Security
from investor_platform.performance.income import dividend_receivables, market_dividends

EX = date(2026, 1, 5)
PAY = date(2026, 1, 6)


def evidence(**changes):
    return {
        "ex_date": EX.isoformat(),
        "pay_date": PAY.isoformat(),
        "gross_per_share": "1.20625",
        "currency": "USD",
        "status": "final",
        "source_url": "https://issuer.example/distributions/2026",
        "reviewed_on": "2026-02-01",
        **changes,
    }


def inputs(reviews):
    security = Security(
        id=uuid4(),
        ticker="DEMO",
        exchange="NYSE",
        currency="USD",
        market_identity={"reviewed_dividends": reviews},
    )
    entries = [
        LedgerEntry(
            kind="buy",
            effective_date=date(2026, 1, 2),
            security_id=security.id,
            quantity=Decimal(10),
            amount=Decimal(100),
        ),
        LedgerEntry(
            kind="income",
            income_kind="dividend",
            income_security_id=security.id,
            effective_date=PAY,
            accrual_date=EX,
            amount=Decimal("12.06"),
        ),
    ]
    prices = {security.id: History({}, {}, dividends={EX: Decimal("1.2")})}
    return security, entries, prices


def test_final_review_reconciles_receivables_without_changing_provider_estimate():
    security, entries, prices = inputs([evidence()])
    original = deepcopy(prices)
    receivables, warnings = dividend_receivables(
        entries, prices, {security.id: security}, [EX, PAY]
    )
    assert warnings == []
    assert receivables == {EX: Decimal("12.06"), PAY: Decimal(0)}
    assert prices == original
    assert market_dividends(entries, prices, PAY) == {(security.id, EX): Decimal(12)}


@pytest.mark.parametrize(
    "case",
    ["other_date", "other_security", "material_shortfall", "missing_event", "missing_record"],
)
def test_review_does_not_clear_unrelated_or_unresolved_dividends(case):
    security, entries, prices = inputs([evidence()])
    securities = {security.id: security}
    if case == "other_date":
        security.market_identity = {"reviewed_dividends": [evidence(ex_date="2026-01-04")]}
    elif case == "other_security":
        other = Security(
            id=uuid4(),
            ticker="OTHER",
            exchange="NYSE",
            currency="USD",
            market_identity=security.market_identity,
        )
        security.market_identity = None
        securities[other.id] = other
    elif case == "material_shortfall":
        entries[-1].amount = Decimal("8.06")
    elif case == "missing_event":
        prices[security.id].dividends = {}
    elif case == "missing_record":
        entries.pop()
    _, warnings = dividend_receivables(entries, prices, securities, [EX, PAY])
    assert len(warnings) == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"currency": "EUR"},
        {"status": "preliminary"},
        {"gross_per_share": "NaN"},
        {"gross_per_share": "0"},
        {"gross_per_share": "-1"},
        {"source_url": ""},
        {"pay_date": "2026-01-04"},
        {"ex_date": "not-a-date"},
        {"unreviewed": True},
    ],
)
def test_invalid_review_is_rejected(changes):
    security, entries, prices = inputs([evidence(**changes)])
    with pytest.raises(ValueError):
        dividend_receivables(entries, prices, {security.id: security}, [EX, PAY])


def test_duplicate_review_is_rejected():
    security, entries, prices = inputs([evidence(), evidence(gross_per_share="1.3")])
    with pytest.raises(ValueError, match="Duplicate"):
        dividend_receivables(entries, prices, {security.id: security}, [EX, PAY])


@pytest.mark.parametrize("reviews", [None, {}, "not-a-list"])
def test_review_collection_must_be_a_list(reviews):
    security, entries, prices = inputs(reviews)
    with pytest.raises(ValueError):
        dividend_receivables(entries, prices, {security.id: security}, [EX, PAY])


def test_review_uses_prior_day_shares_and_retains_unclassified_income_warning():
    security, entries, prices = inputs([evidence()])
    entries.append(
        LedgerEntry(
            kind="buy",
            effective_date=EX,
            security_id=security.id,
            quantity=Decimal(5),
            amount=Decimal(50),
        )
    )
    entries.append(LedgerEntry(kind="income", effective_date=PAY, amount=Decimal(1)))
    receivables, warnings = dividend_receivables(
        entries, prices, {security.id: security}, [EX, PAY]
    )
    assert receivables[EX] == Decimal("12.06")
    assert warnings == ["Classify recorded income as dividends, interest or other income."]
