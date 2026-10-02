from datetime import date
from decimal import Decimal as D
from uuid import uuid4

import pytest
from test_ledger import cash, ledger
from test_trades import trade

from investor_platform import market
from investor_platform.market import History

DAYS = [date(2026, 1, 2), date(2026, 1, 5), date(2026, 1, 6)]


@pytest.fixture
def portfolio(db_client, monkeypatch):
    aid = db_client.post(
        "/api/account", json={"name": "Performance fixture", "base_currency": "USD"}
    ).json()["id"]
    assert cash(db_client, aid, "opening_cash", "1000", day="2026-01-02").status_code == 201
    assert (
        trade(db_client, aid, quantity="10", price="100", ticker="AAA", exchange="NYSE").status_code
        == 201
    )
    data = {
        "AAA": History(
            dict(zip(DAYS, map(D, ["100", "110", "121"]))),
            dict(zip(DAYS, map(D, ["100", "110", "121"]))),
        ),
        "SPY": History(
            dict(zip(DAYS, map(D, ["100", "100", "101"]))),
            dict(zip(DAYS, map(D, ["100", "101", "102"]))),
        ),
        "QQQ": History(
            dict(zip(DAYS, map(D, ["100", "102", "104"]))),
            dict(zip(DAYS, map(D, ["100", "102", "104"]))),
        ),
    }
    data["AAA"].exchange = "NYQ"
    data["SPY"].exchange = "PCX"
    data["QQQ"].exchange = "NGM"
    monkeypatch.setattr(market, "history", lambda symbol, start, end: data[symbol])
    return aid, data


def report(client, aid, start="2026-01-02", end="2026-01-06"):
    return client.post(f"/api/accounts/{aid}/performance", json={"start": start, "end": end})


def test_cash_flow_adjusted_returns_and_adjusted_benchmarks(db_client, portfolio):
    aid, _ = portfolio
    cash(db_client, aid, amount="1000", day="2026-01-05")
    cash(db_client, aid, "withdrawal", "200", day="2026-01-06")
    r = report(db_client, aid)
    assert r.status_code == 200, r.text
    result = r.json()
    assert D(result["value"]) == 2010
    assert float(result["return"]) == pytest.approx(1.1 * 2210 / 2100 - 1)
    assert D(result["SPY"]) == D(".02")  # Adjusted, not raw close.
    assert D(result["QQQ"]) == D(".04")
    assert D(result["holdings"][0]["unrealized_pnl"]) == 210
    assert D(result["holdings"][0]["weight"]) == pytest.approx(D(1210) / D(2010))


def test_income_is_return_and_unreconciled_distributions_block_returns(db_client, portfolio):
    aid, data = portfolio
    data["AAA"].dividends[DAYS[1]] = D("1")
    first = report(db_client, aid).json()
    assert first["return"] is None and first["excess_spy"] is None
    assert all(p["portfolio"] is None for p in first["series"])
    # Also reconcile income before the requested reporting period.
    assert report(db_client, aid, start="2026-01-05").json()["return"] is None
    assert cash(db_client, aid, "income", "10", day="2026-01-05").status_code == 201
    assert D(ledger(db_client, aid)["balance"]) == 10
    result = report(db_client, aid).json()
    assert result["warnings"] == []
    assert D(result["return"]) == D(".22")
    assert D(result["value"]) == 1220


@pytest.mark.parametrize(
    "problem", ["missing", "split", "benchmark_gap", "outage", "currency", "exchange"]
)
def test_incomplete_market_inputs_fail_closed(db_client, portfolio, monkeypatch, problem):
    aid, data = portfolio
    if problem == "missing":
        del data["AAA"].close[DAYS[1]]
    elif problem == "split":
        data["AAA"].splits.add(DAYS[1])
    elif problem == "benchmark_gap":
        del data["QQQ"].adjusted[DAYS[1]]
    elif problem == "exchange":
        data["AAA"].exchange = "NMS"
    elif problem == "outage":

        def unavailable(*args):
            raise OSError("offline")

        monkeypatch.setattr(market, "history", unavailable)
    else:
        trade(db_client, aid, "opening_position", "1", ticker="FOREIGN", exchange="TSX")
    before = ledger(db_client, aid)
    r = report(db_client, aid)
    assert r.status_code == (503 if problem == "outage" else 422)
    assert ledger(db_client, aid) == before


def test_dates_ownership_and_in_kind_flows(db_client, portfolio):
    aid, _ = portfolio
    assert report(db_client, str(uuid4())).status_code == 404
    assert report(db_client, aid, start="2026-01-01").status_code == 422
    assert report(db_client, aid, end="2099-01-01").status_code == 422
    assert report(db_client, aid, end="2026-01-02").status_code == 422
    # Contributions in shares are valued at the closing price, not their tax basis.
    assert (
        trade(
            db_client,
            aid,
            "opening_position",
            "2",
            ticker="SPY",
            exchange="ARCA",
            effective_date="2026-01-05",
            cost_basis="1",
        ).status_code
        == 201
    )
    r = report(db_client, aid).json()
    assert float(r["series"][1]["portfolio"]) == pytest.approx(0.1)


def test_zero_balance_breaks_a_continuous_return_period(db_client, portfolio):
    aid, _ = portfolio
    assert (
        trade(
            db_client,
            aid,
            "sell",
            "10",
            "110",
            ticker="AAA",
            exchange="NYSE",
            effective_date="2026-01-05",
        ).status_code
        == 201
    )
    assert cash(db_client, aid, "withdrawal", "1100", day="2026-01-05").status_code == 201
    assert cash(db_client, aid, amount="100", day="2026-01-06").status_code == 201
    result = report(db_client, aid)
    assert result.status_code == 422
    assert "zero-value balance" in result.json()["detail"]
