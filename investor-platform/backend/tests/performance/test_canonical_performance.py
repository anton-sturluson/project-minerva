"""Whole-account performance from canonical dated, explicitly inferred cash records."""

from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from helpers import DAYS, cash, dividend, ledger, stock_report, trade
from httpx import Response
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from investor_platform.domain import EntryKind
from investor_platform.market_data.types import History
from investor_platform.models import Account, LedgerEntry


@pytest.fixture
def canonical_portfolio(
    portfolio: tuple[str, dict[str, History]], database: Engine
) -> tuple[str, dict[str, History]]:
    """Use a real dated deposit and retain inferred funding provenance in a test account."""
    account_id: str = portfolio[0]
    session: Session
    with Session(database) as session:
        account: Account = session.get(Account, UUID(account_id))
        account.reconstruction = {
            "cash_method": "purchase_shortfall",
            "funding_status": "inferred",
            "warning": "Synthetic imported data",
            "source_sha256": "synthetic",
            "imported_trades": 1,
            "skipped": [],
            "opening_positions": {},
            "price_discrepancies": [],
        }
        opening: LedgerEntry = session.scalar(
            select(LedgerEntry).where(
                LedgerEntry.account_id == UUID(account_id),
                LedgerEntry.kind == EntryKind.OPENING_CASH,
            )
        )
        opening.kind = EntryKind.DEPOSIT
        session.commit()
    return portfolio


def test_canonical_account_reuses_sales_and_preserves_returns_between_index_choices(
    db_client: TestClient, canonical_portfolio: tuple[str, dict[str, History]]
) -> None:
    """A fully reinvested sale stays internal rather than diluting return with gross flows."""
    account_id: str = canonical_portfolio[0]
    assert (
        trade(
            db_client,
            account_id,
            "sell",
            "10",
            "110",
            ticker="AAA",
            exchange="NYSE",
            effective_date=str(DAYS[1]),
        ).status_code
        == 201
    )
    assert (
        trade(
            db_client,
            account_id,
            "buy",
            "10",
            "110",
            ticker="AAA",
            exchange="NYSE",
            effective_date=str(DAYS[1]),
        ).status_code
        == 201
    )
    before: dict = ledger(db_client, account_id)
    regular_response: Response = stock_report(
        db_client, account_id, scope="account", benchmark_mode="buy_hold"
    )
    funded_response: Response = stock_report(
        db_client, account_id, scope="account", benchmark_mode="funded_hold"
    )
    assert regular_response.status_code == funded_response.status_code == 200
    regular: dict = regular_response.json()
    funded: dict = funded_response.json()
    field: str
    for field in ("cash", "value", "return", "holdings", "start", "end", "blockers"):
        assert regular[field] == funded[field]
    assert Decimal(regular["series"][1]["portfolio"]) == Decimal(".1")
    assert Decimal(regular["return"]) == Decimal(".21")
    assert Decimal(regular["cash"]) == 0
    assert Decimal(funded["benchmark_values"]["SPY"]["value"]) == 1020
    assert regular["funding_status"] == "inferred"
    assert regular["cash_method"] == "purchase_shortfall"
    assert "funding_estimate" not in regular
    assert ledger(db_client, account_id) == before
    account: dict = db_client.get("/api/accounts").json()[0]
    assert account["reconstruction"]["cash_method"] == "purchase_shortfall"
    assert account["reconstruction"]["opening_cash"] is None


def test_canonical_funding_does_not_hide_missing_dividend_records(
    db_client: TestClient, canonical_portfolio: tuple[str, dict[str, History]]
) -> None:
    """An inferred funding policy cannot certify missing investment income."""
    account_id: str = canonical_portfolio[0]
    canonical_portfolio[1]["AAA"].dividends[DAYS[1]] = Decimal(1)
    mode: str
    for mode in ("buy_hold", "funded_hold"):
        response: Response = stock_report(
            db_client, account_id, scope="account", benchmark_mode=mode
        )
        assert response.status_code == 200
        result: dict = response.json()
        assert result["return"] is None
        assert result["warnings"] == result["blockers"]
        assert result["cagr"]["portfolio"] is None
        assert any("reconcile dividend" in warning for warning in result["blockers"])
        assert all(point["portfolio"] is None for point in result["series"])


def test_canonical_dividend_receivable_is_income_without_early_spendable_cash(
    db_client: TestClient, canonical_portfolio: tuple[str, dict[str, History]]
) -> None:
    """Earned dividends enter wealth once and become cash only on the recorded payment date."""
    account_id: str = canonical_portfolio[0]
    canonical_portfolio[1]["AAA"].dividends[DAYS[1]] = Decimal(1)
    assert dividend(db_client, account_id, pay=str(DAYS[2]), ex=str(DAYS[1])).status_code == 201
    response: Response = stock_report(
        db_client, account_id, scope="account", benchmark_mode="funded_hold"
    )
    assert response.status_code == 200
    result: dict = response.json()
    assert result["blockers"] == []
    assert Decimal(result["series"][1]["cash"]) == 0
    assert Decimal(result["series"][1]["receivables"]) == 10
    assert Decimal(result["cash"]) == 10
    assert Decimal(result["return"]) == Decimal(".22")
    assert Decimal(result["benchmark_values"]["SPY"]["value"]) == 1020


def test_canonical_marker_cannot_ignore_an_active_opening_placeholder(
    db_client: TestClient, canonical_portfolio: tuple[str, dict[str, History]], database: Engine
) -> None:
    """Changing metadata cannot silently discard a real active ledger cash entry."""
    account_id: str = canonical_portfolio[0]
    session: Session
    with Session(database) as session:
        deposit: LedgerEntry = session.scalar(
            select(LedgerEntry).where(
                LedgerEntry.account_id == UUID(account_id), LedgerEntry.kind == EntryKind.DEPOSIT
            )
        )
        deposit.kind = EntryKind.OPENING_CASH
        session.commit()
    response: Response = stock_report(db_client, account_id, scope="account")
    assert response.status_code == 422
    assert "opening placeholder" in response.json()["detail"]


def test_canonical_cash_withdrawal_only_blocks_the_never_sold_index_simulation(
    db_client: TestClient, canonical_portfolio: tuple[str, dict[str, History]]
) -> None:
    """Ordinary account returns still support withdrawals without inventing index sales."""
    account_id: str = canonical_portfolio[0]
    assert cash(db_client, account_id, amount="100", day=str(DAYS[1])).status_code == 201
    assert cash(db_client, account_id, "withdrawal", "100", day=str(DAYS[2])).status_code == 201
    ordinary: Response = stock_report(db_client, account_id, scope="account")
    funded: Response = stock_report(
        db_client, account_id, scope="account", benchmark_mode="funded_hold"
    )
    assert ordinary.status_code == 200
    assert ordinary.json()["return"] is not None
    assert funded.status_code == 422
    assert "withdrawals" in funded.json()["detail"]


@pytest.mark.parametrize("recent", [False, True])
def test_canonical_period_rebases_returns_without_rebuilding_funding(
    db_client: TestClient,
    canonical_portfolio: tuple[str, dict[str, History]],
    recent: bool,
) -> None:
    """Reporting dates change the measured interval while keeping actual account wealth fixed."""
    account_id: str = canonical_portfolio[0]
    ordinary: dict = stock_report(
        db_client,
        account_id,
        scope="account",
        benchmark_mode="buy_hold",
        start=str(DAYS[1] if recent else DAYS[0]),
        baseline="recorded" if recent else "history",
    ).json()
    funded: dict = stock_report(
        db_client,
        account_id,
        scope="account",
        benchmark_mode="funded_hold",
        start=str(DAYS[1] if recent else DAYS[0]),
        baseline="recorded" if recent else "history",
    ).json()
    assert ordinary["start"] == funded["start"] == str(DAYS[1] if recent else DAYS[0])
    assert Decimal(ordinary["value"]) == Decimal(funded["value"]) == 1210
    assert (
        Decimal(ordinary["return"])
        == Decimal(funded["return"])
        == (Decimal(".1") if recent else Decimal(".21"))
    )
    fields: tuple[str, ...] = ("date", "portfolio", "cash", "value", "receivables")
    assert [tuple(point[field] for field in fields) for point in ordinary["series"]] == [
        tuple(point[field] for field in fields) for point in funded["series"]
    ]
    assert Decimal(funded["benchmark_values"]["SPY"]["value"]) == 1020


def test_canonical_share_receipt_is_neutralized_at_close_in_both_comparisons(
    db_client: TestClient, canonical_portfolio: tuple[str, dict[str, History]]
) -> None:
    """Received shares contribute market value once without becoming available cash."""
    account_id: str = canonical_portfolio[0]
    assert (
        trade(
            db_client,
            account_id,
            "transfer_in",
            "2",
            ticker="SPY",
            exchange="ARCA",
            effective_date=str(DAYS[1]),
            cost_basis="1",
        ).status_code
        == 201
    )
    ordinary: dict = stock_report(db_client, account_id, scope="account").json()
    funded: dict = stock_report(
        db_client, account_id, scope="account", benchmark_mode="funded_hold"
    ).json()
    assert ordinary["return"] == funded["return"]
    assert Decimal(funded["series"][1]["portfolio"]) == Decimal(".1")
    assert Decimal(funded["cash"]) == 0
    assert float(funded["benchmark_values"]["SPY"]["value"]) == pytest.approx(
        (10 + 200 / 101) * 102
    )
    assert float(funded["SPY"]) == pytest.approx(0.02)


@pytest.fixture
def zero_dividend_portfolio(
    canonical_portfolio: tuple[str, dict[str, History]], database: Engine
) -> tuple[str, dict[str, History]]:
    """Enable the explicit temporary assumption for one synthetic imported account."""
    session: Session
    with Session(database) as session:
        account: Account = session.get(Account, UUID(canonical_portfolio[0]))
        account.reconstruction = account.reconstruction | {"dividend_policy": "unrecorded_zero"}
        session.commit()
    return canonical_portfolio


def test_zero_unrecorded_dividends_is_explicit_and_index_independent(
    db_client: TestClient, zero_dividend_portfolio: tuple[str, dict[str, History]]
) -> None:
    """Missing dividends add no wealth or cash and the same assumption applies to scenarios."""
    account_id: str = zero_dividend_portfolio[0]
    zero_dividend_portfolio[1]["AAA"].dividends[DAYS[1]] = Decimal(1)
    before: dict = ledger(db_client, account_id)
    sid: str = before["holdings"][0]["security"]["id"]
    reports: list[dict] = []
    mode: str
    for mode in ("buy_hold", "funded_hold"):
        response: Response = stock_report(
            db_client, account_id, scope="account", benchmark_mode=mode, exclude_security_ids=[sid]
        )
        assert response.status_code == 200, response.text
        result: dict = response.json()
        assert result["blockers"] == []
        assert result["dividend_policy"] == "unrecorded_zero"
        assert any("unrecorded dividends are zero" in item for item in result["assumptions"])
        assert Decimal(result["return"]) == Decimal(".21")
        assert Decimal(result["value"]) == 1210 and Decimal(result["cash"]) == 0
        assert Decimal(result["receivables"]) == 0
        assert result["scenario"]["dividend_policy"] == "unrecorded_zero"
        assert Decimal(result["scenario"]["return"]) == 0
        reports.append(result)
    assert reports[0]["series"][1]["portfolio"] == reports[1]["series"][1]["portfolio"]
    assert reports[0]["return"] == reports[1]["return"]
    assert reports[0]["cagr"]["portfolio"] == reports[1]["cagr"]["portfolio"]
    assert ledger(db_client, account_id) == before
    account: dict = db_client.get("/api/accounts").json()[0]
    assert account["reconstruction"]["dividend_policy"] == "unrecorded_zero"


def test_zero_policy_retains_actual_dividends_and_receivables(
    db_client: TestClient, zero_dividend_portfolio: tuple[str, dict[str, History]]
) -> None:
    """Recorded dividends count once while another missing distribution contributes zero."""
    account_id: str = zero_dividend_portfolio[0]
    zero_dividend_portfolio[1]["AAA"].dividends[DAYS[1]] = Decimal(1)
    zero_dividend_portfolio[1]["AAA"].dividends[DAYS[2]] = Decimal(2)
    assert dividend(db_client, account_id, pay=str(DAYS[2]), ex=str(DAYS[1])).status_code == 201
    before: dict = ledger(db_client, account_id)
    result: dict = stock_report(db_client, account_id, scope="account").json()
    assert result["blockers"] == []
    assert Decimal(result["series"][1]["receivables"]) == 10
    assert Decimal(result["series"][1]["cash"]) == 0
    assert Decimal(result["return"]) == Decimal(".22")
    assert Decimal(result["cash"]) == 10 and Decimal(result["value"]) == 1220
    assert ledger(db_client, account_id) == before


@pytest.mark.parametrize("problem", ["amount", "unmatched", "unclassified"])
def test_zero_policy_preserves_source_advisories_and_method_blockers(
    db_client: TestClient,
    zero_dividend_portfolio: tuple[str, dict[str, History]],
    problem: str,
) -> None:
    """Zero-unrecorded policy preserves source differences and blocks missing accrual inputs."""
    account_id: str = zero_dividend_portfolio[0]
    zero_dividend_portfolio[1]["AAA"].dividends[DAYS[1]] = Decimal(1)
    if problem == "amount":
        assert dividend(db_client, account_id, amount="9").status_code == 201
    elif problem == "unmatched":
        assert dividend(db_client, account_id, ex=str(DAYS[0])).status_code == 201
    else:
        assert cash(db_client, account_id, "income", "5", day=str(DAYS[2])).status_code == 201
    mode: str
    for mode in ("buy_hold", "funded_hold"):
        response: Response = stock_report(
            db_client, account_id, scope="account", benchmark_mode=mode
        )
        assert response.status_code == 200, response.text
        result: dict = response.json()
        if problem == "amount":
            assert result["blockers"] == []
            assert len(result["advisories"]) == 1
            assert float(result["return"]) == pytest.approx(0.219)
            assert Decimal(result["cash"]) == 9
            assert Decimal(result["value"]) == 1219
        else:
            assert result["blockers"]
            assert result["return"] is None and result["cagr"]["portfolio"] is None
            assert all(point["portfolio"] is None for point in result["series"])
        assert result["dividend_policy"] == "unrecorded_zero"


def test_account_zero_policy_does_not_relabel_the_analytic_stock_sleeve(
    db_client: TestClient, zero_dividend_portfolio: tuple[str, dict[str, History]]
) -> None:
    """Analytic stocks retain their provider-estimated distributions and their own disclosure."""
    account_id: str = zero_dividend_portfolio[0]
    zero_dividend_portfolio[1]["AAA"].dividends[DAYS[1]] = Decimal(1)
    result: dict = stock_report(db_client, account_id).json()
    assert "dividend_policy" not in result
    assert not any("unrecorded dividends are zero" in item for item in result["assumptions"])
    assert float(result["return"]) == pytest.approx((111 / 100) * (121 / 110) - 1)


@pytest.mark.parametrize(
    "provider_rate, advisory_count",
    [
        (Decimal("1.2"), 1),
        (Decimal("1.9"), 1),
        (None, 1),
        (Decimal("1.2054"), 1),
        (Decimal("1.2056"), 0),
    ],
)
def test_recorded_income_drives_default_account_return_with_source_advisories(
    db_client: TestClient,
    canonical_portfolio: tuple[str, dict[str, History]],
    provider_rate: Decimal | None,
    advisory_count: int,
) -> None:
    """Rounded, conflicting and missing provider rates cannot replace recorded income."""
    account_id, histories = canonical_portfolio
    if provider_rate is not None:
        histories["AAA"].dividends[DAYS[1]] = provider_rate
    assert dividend(db_client, account_id, "12.06").status_code == 201
    before: dict = ledger(db_client, account_id)
    response: Response = db_client.post(
        f"/api/accounts/{account_id}/performance",
        json={
            "start": str(DAYS[0]),
            "end": str(DAYS[-1]),
            "scope": "account",
            "benchmark_mode": "funded_hold",
        },
    )
    assert response.status_code == 200, response.text
    result: dict = response.json()
    assert result["blockers"] == []
    assert len(result["advisories"]) == advisory_count
    assert result["warnings"] == result["blockers"] == []
    if provider_rate is None:
        assert "no matching provider event" in result["advisories"][0]
    elif advisory_count:
        assert f"provider estimate {provider_rate * 10:.2f}" in result["advisories"][0]
        assert "recorded gross 12.06" in result["advisories"][0]
    assert Decimal(result["return"]) == Decimal(".22206")
    assert Decimal(result["value"]) == Decimal("1222.06")
    assert Decimal(result["cash"]) == Decimal("12.06")
    assert Decimal(result["series"][1]["cash"]) == 0
    assert Decimal(result["series"][1]["receivables"]) == Decimal("12.06")
    assert result["series"][-1]["receivables"] == "0"
    assert Decimal(result["excess_spy"]) == Decimal(".20206")
    assert ledger(db_client, account_id) == before


def test_next_month_source_disagreement_needs_no_per_event_override(
    db_client: TestClient, canonical_portfolio: tuple[str, dict[str, History]]
) -> None:
    """New monthly income follows the same recorded-cash rule without stored exceptions."""
    account_id, histories = canonical_portfolio
    histories["AAA"].dividends[DAYS[1]] = Decimal("1.2")
    assert dividend(db_client, account_id, "12.06").status_code == 201
    for history in histories.values():
        for day in (date(2026, 2, 5), date(2026, 2, 6)):
            history.close[day] = history.close[DAYS[-1]]
            history.adjusted[day] = history.adjusted[DAYS[-1]]
    histories["AAA"].dividends[date(2026, 2, 5)] = Decimal("1.21")
    assert (
        dividend(db_client, account_id, "12.12", ex="2026-02-05", pay="2026-02-06").status_code
        == 201
    )
    before: dict = ledger(db_client, account_id)
    response: Response = stock_report(
        db_client, account_id, scope="account", benchmark_mode="funded_hold", end="2026-02-06"
    )
    assert response.status_code == 200, response.text
    result: dict = response.json()
    assert result["blockers"] == []
    assert len(result["advisories"]) == 2
    assert Decimal(result["cash"]) == Decimal("24.18")
    assert Decimal(result["value"]) == Decimal("1234.18")
    assert Decimal(result["return"]) == Decimal(".23418")
    assert ledger(db_client, account_id) == before


def test_source_advisory_preserves_annualized_account_return(
    db_client: TestClient, canonical_portfolio: tuple[str, dict[str, History]], database: Engine
) -> None:
    """Long-period CAGR uses the numeric recorded return even when source checks remain."""
    account_id, histories = canonical_portfolio
    start: date = date(2025, 1, 2)
    with Session(database) as session:
        for entry in session.scalars(
            select(LedgerEntry).where(LedgerEntry.account_id == UUID(account_id))
        ):
            entry.effective_date = start
        session.commit()
    for history in histories.values():
        history.close[start] = history.close.pop(DAYS[0])
        history.adjusted[start] = history.adjusted.pop(DAYS[0])
    histories["AAA"].dividends[DAYS[1]] = Decimal("1.2")
    assert dividend(db_client, account_id, "12.06").status_code == 201
    response: Response = stock_report(
        db_client, account_id, scope="account", benchmark_mode="funded_hold", start=str(start)
    )
    assert response.status_code == 200, response.text
    result: dict = response.json()
    assert result["blockers"] == [] and len(result["advisories"]) == 1
    assert Decimal(result["return"]) == Decimal(".22206")
    assert float(result["cagr"]["portfolio"]) == pytest.approx(1.22206 ** (365.25 / 369) - 1)


@pytest.mark.parametrize("provider_rate, available", [(Decimal(1), True), (Decimal(10), False)])
def test_strict_income_check_requires_a_payable_cent_for_fractional_shares(
    db_client: TestClient,
    canonical_portfolio: tuple[str, dict[str, History]],
    database: Engine,
    provider_rate: Decimal,
    available: bool,
) -> None:
    """A zero-cent entitlement needs no impossible zero-income row; positive cents still block."""
    account_id, histories = canonical_portfolio
    with Session(database) as session:
        for entry in session.scalars(
            select(LedgerEntry).where(LedgerEntry.account_id == UUID(account_id))
        ):
            entry.amount = Decimal(".1")
            if entry.kind == EntryKind.BUY:
                entry.quantity = Decimal(".001")
        session.commit()
    histories["AAA"].dividends[DAYS[1]] = provider_rate
    before: dict = ledger(db_client, account_id)
    response: Response = stock_report(
        db_client, account_id, scope="account", benchmark_mode="funded_hold"
    )
    assert response.status_code == 200, response.text
    result: dict = response.json()
    assert Decimal(result["cash"]) == 0
    assert Decimal(result["receivables"]) == 0
    assert Decimal(result["value"]) == Decimal(".121")
    assert result["advisories"] == []
    if available:
        assert result["blockers"] == []
        assert Decimal(result["return"]) == Decimal(".21")
    else:
        assert len(result["blockers"]) == 1
        assert result["return"] is None
    assert ledger(db_client, account_id) == before
