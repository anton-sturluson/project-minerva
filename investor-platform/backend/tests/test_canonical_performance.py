"""Whole-account performance from canonical dated, explicitly inferred cash records."""

from decimal import Decimal
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from helpers import DAYS, cash, dividend, ledger, stock_report, trade
from httpx import Response
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from investor_platform.domain import EntryKind
from investor_platform.market import History
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
    for field in ("cash", "value", "return", "holdings", "start", "end", "warnings"):
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
        assert result["cagr"]["portfolio"] is None
        assert any("reconcile dividend" in warning for warning in result["warnings"])
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
    assert result["warnings"] == []
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
