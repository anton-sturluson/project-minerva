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
        "/api/accounts", json={"name": "Performance fixture", "base_currency": "USD"}
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
        trade(db_client, aid, "opening_position", "1", ticker="FOREIGN", exchange="UNSUPPORTED")
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


def test_provisional_comparison_models_only_missing_income_without_writing(
    db_client, portfolio, database
):
    from uuid import UUID

    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from investor_platform.models import Account, Security

    aid, data = portfolio
    with Session(database) as session:
        session.get(Account, UUID(aid)).reconstruction = {
            "testing": True,
            "funding_status": "reconciled",
        }
        session.scalar(select(Security).where(Security.ticker == "AAA")).exchange = "UNVERIFIED"
        session.commit()
    data["AAA"].dividends[DAYS[1]] = D("1")
    assert cash(db_client, aid, "income", "4", day="2026-01-05").status_code == 201
    before = ledger(db_client, aid)
    result = report(db_client, aid).json()
    assert result["provisional"] is True
    assert result["assumptions"]
    assert D(result["modeled_income"]) == 6
    assert D(result["value"]) == 1220
    assert D(result["return"]) == D(".22")
    assert D(result["excess_spy"]) == D(".20")
    assert ledger(db_client, aid) == before
    # Modeling never relaxes missing-price or corporate-action safeguards.
    data["AAA"].splits.add(DAYS[1])
    assert report(db_client, aid).status_code == 422
    data["AAA"].splits.clear()
    del data["AAA"].close[DAYS[1]]
    assert report(db_client, aid).status_code == 422


def scenario(client, aid, excluded, **period):
    return client.post(
        f"/api/accounts/{aid}/performance",
        json={
            "start": "2026-01-02",
            "end": "2026-01-06",
            "exclude_security_ids": excluded,
            **period,
        },
    )


def test_excluding_a_stock_removes_all_trades_and_fees_but_preserves_flows(db_client, portfolio):
    aid, _ = portfolio
    cash(db_client, aid, amount="100", day="2026-01-05")
    trade(
        db_client,
        aid,
        "sell",
        "5",
        "110",
        ticker="AAA",
        exchange="NYSE",
        fees="2",
        effective_date="2026-01-05",
    )
    cash(db_client, aid, "withdrawal", "50", day="2026-01-06")
    before = ledger(db_client, aid)
    sid = before["holdings"][0]["security"]["id"]
    result = scenario(db_client, aid, [sid]).json()
    alternative = result["scenario"]
    assert D(alternative["cash"]) == 1050
    assert D(alternative["return"]) == 0
    assert alternative["holdings"] == []
    assert alternative["SPY"] == result["SPY"]
    assert alternative["excluded"][0]["id"] == sid
    # A later window must still undo excluded trades from before that window.
    later = scenario(db_client, aid, [sid], start="2026-01-05").json()["scenario"]
    assert D(later["cash"]) == 1050 and D(later["return"]) == 0
    assert ledger(db_client, aid) == before


def test_scenario_converts_opening_shares_to_cash_and_preserves_other_positions(
    db_client, portfolio
):
    aid, _ = portfolio
    trade(
        db_client,
        aid,
        "opening_position",
        "2",
        ticker="SPY",
        exchange="ARCA",
        effective_date="2026-01-03",
    )
    before = ledger(db_client, aid)
    sid = next(h["security"]["id"] for h in before["holdings"] if h["security"]["ticker"] == "SPY")
    result = scenario(db_client, aid, [sid]).json()
    alternative = result["scenario"]
    assert D(alternative["cash"]) == 200  # First session after the weekend, not cost basis.
    assert D(alternative["value"]) == 1410
    assert [h["ticker"] for h in alternative["holdings"]] == ["AAA"]
    assert float(alternative["return"]) == pytest.approx(1.1 * 1410 / 1300 - 1)
    assert ledger(db_client, aid) == before


def test_excluded_stock_does_not_contribute_modeled_dividends(db_client, portfolio, database):
    from uuid import UUID

    from sqlalchemy.orm import Session

    from investor_platform.models import Account

    aid, data = portfolio
    with Session(database) as session:
        session.get(Account, UUID(aid)).reconstruction = {
            "testing": True,
            "funding_status": "reconciled",
        }
        session.commit()
    data["AAA"].dividends[DAYS[1]] = D("1")
    before = ledger(db_client, aid)
    result = scenario(db_client, aid, [before["holdings"][0]["security"]["id"]]).json()
    assert D(result["modeled_income"]) == 10
    assert D(result["scenario"]["modeled_income"]) == 0
    assert D(result["scenario"]["return"]) == 0
    assert ledger(db_client, aid) == before


@pytest.mark.parametrize("problem", ["income", "funding"])
def test_invalid_scenario_keeps_original_report_and_ledger(db_client, portfolio, problem):
    aid, _ = portfolio
    sid = ledger(db_client, aid)["holdings"][0]["security"]["id"]
    if problem == "income":
        cash(db_client, aid, "income", "10", day="2026-01-05")
    else:
        trade(
            db_client,
            aid,
            "sell",
            "10",
            "110",
            ticker="AAA",
            exchange="NYSE",
            effective_date="2026-01-05",
        )
        cash(db_client, aid, "withdrawal", "1050", day="2026-01-05")
    before = ledger(db_client, aid)
    result = scenario(db_client, aid, [sid])
    assert result.status_code == 200
    assert result.json()["scenario"] is None
    assert result.json()["scenario_error"]
    assert result.json()["return"] is not None
    assert ledger(db_client, aid) == before


def test_scenario_rejects_unknown_security_and_deduplicates_selection(db_client, portfolio):
    aid, _ = portfolio
    assert scenario(db_client, aid, [str(uuid4())]).status_code == 422
    sid = ledger(db_client, aid)["holdings"][0]["security"]["id"]
    assert len(scenario(db_client, aid, [sid, sid]).json()["scenario"]["excluded"]) == 1


def test_cagr_annualizes_linked_returns_instead_of_cash_growth(db_client, portfolio):
    aid, data = portfolio
    # Use historical dates so this remains a completed-session API request.
    start = date(2024, 1, 2)
    finish = date(2026, 1, 2)
    from investor_platform.domain import EntryKind
    from investor_platform.models import LedgerEntry
    from investor_platform.performance import annualized_return, calculate

    histories = {
        key: History({start: D(100), finish: D(121)}, {start: D(100), finish: D(121)})
        for key in ("SPY", "QQQ")
    }
    entries = [
        LedgerEntry(
            id=1, kind=EntryKind.OPENING_CASH, amount=D(100), effective_date=start, security_id=None
        ),
        LedgerEntry(
            id=2, kind=EntryKind.DEPOSIT, amount=D(900), effective_date=finish, security_id=None
        ),
    ]
    result = calculate(entries, histories, start, finish)
    assert result["cagr"]["portfolio"] == 0  # A tenfold deposit is not investment growth.
    assert float(result["cagr"]["SPY"]) == pytest.approx(1.21 ** (365.25 / 731) - 1)
    assert annualized_return(D("0.21"), DAYS[0], DAYS[-1]) is None
    assert annualized_return(None, start, finish) is None
    assert annualized_return(D(-1), start, finish) == -1
    # Reconciliation suppression propagates into the public CAGR field too.
    data["AAA"].dividends[DAYS[1]] = D(1)
    assert report(db_client, aid).json()["cagr"]["portfolio"] is None


@pytest.mark.parametrize(
    "exchange,suffix,currency,provider",
    [
        ("ASX", ".AX", "AUD", "ASX"),
        ("TSXV", ".V", "CAD", "VAN"),
        ("TSX", ".TO", "CAD", "TOR"),
        ("XSTO", ".ST", "SEK", "STO"),
        ("FNSE", ".ST", "SEK", "STO"),
    ],
)
def test_foreign_performance_and_scenario_use_dated_fx(
    db_client, portfolio, monkeypatch, exchange, suffix, currency, provider
):
    aid, data = portfolio
    cash(db_client, aid, amount="100", day="2026-01-02")
    trade(db_client, aid, quantity="10", price="7", ticker="FOREIGN", exchange=exchange)
    local = History({DAYS[0]: D(10), DAYS[2]: D(12)}, {}, exchange=provider)
    fx = History(dict(zip(DAYS, map(D, [".7", ".8", ".9"]))), {})

    def quote(symbol, start, end, **kwargs):
        if symbol == "FOREIGN" + suffix:
            assert kwargs == {"currency": currency}
            return local
        if symbol == currency + "USD=X":
            assert kwargs == {"instruments": ("CURRENCY",)}
            return fx
        return data[symbol]

    monkeypatch.setattr(market, "history", quote)
    before = ledger(db_client, aid)
    sid = next(
        h["security"]["id"] for h in before["holdings"] if h["security"]["ticker"] == "FOREIGN"
    )
    result = scenario(db_client, aid, [sid]).json()
    assert D(result["series"][1]["value"]) == 1210  # 1100 domestic + 80 foreign + 30 cash.
    assert D(result["value"]) == 1348
    assert float(result["return"]) == pytest.approx(1348 / 1100 - 1)
    assert D(result["scenario"]["value"]) == 1310
    assert ledger(db_client, aid) == before
    del fx.close[DAYS[1]]
    missing = report(db_client, aid)
    assert missing.status_code == 422 and "Missing close" in missing.json()["detail"]
    assert ledger(db_client, aid) == before


def test_foreign_hit_rate_requires_actual_trade_sessions_not_holiday_carries(
    db_client, portfolio, monkeypatch
):
    aid, data = portfolio
    cash(db_client, aid, amount="100", day="2026-01-02")
    trade(db_client, aid, quantity="1", price="10", ticker="FOREIGN", exchange="TSX")
    trade(
        db_client,
        aid,
        "sell",
        "1",
        "12",
        ticker="FOREIGN",
        exchange="TSX",
        effective_date="2026-01-05",
    )

    def quote(symbol, start, end, **kwargs):
        if symbol == "FOREIGN.TO":
            assert kwargs == {"currency": "CAD"}
            return History({DAYS[0]: D(15), DAYS[2]: D(16)}, {}, exchange="TOR")
        assert not symbol.endswith("=X")  # Recorded USD cash needs no FX conversion.
        return data[symbol]

    monkeypatch.setattr(market, "history", quote)
    result = db_client.post(f"/api/accounts/{aid}/hit-rate").json()
    assert result["excluded"] == 1
    assert "Missing matching closing prices" in result["episodes"][0]["excluded"]


def test_recorded_baseline_needs_no_closed_history_but_keeps_cash_and_current_safeguards(
    db_client, portfolio, monkeypatch
):
    aid, data = portfolio
    trade(db_client, aid, "opening_position", "1", ticker="OLD", exchange="NYSE", cost_basis="10")
    trade(db_client, aid, "sell", "1", "50", ticker="OLD", exchange="NYSE")
    cash(db_client, aid, amount="100", day="2026-01-05")
    before = ledger(db_client, aid)
    calls = []

    def quote(symbol, start, end):
        calls.append(symbol)
        if symbol == "OLD":
            raise OSError("delisted")
        return data[symbol]

    monkeypatch.setattr(market, "history", quote)
    assert report(db_client, aid).status_code == 503
    calls.clear()
    url = f"/api/accounts/{aid}/performance"
    period = {"start": "2026-01-05", "end": "2026-01-06", "baseline": "recorded"}
    result = db_client.post(url, json=period)
    assert result.status_code == 200, result.text
    r = result.json()
    assert "OLD" not in calls
    assert r["baseline"] == "recorded"
    assert D(r["cash"]) == 150  # Keeps past sale proceeds and the new deposit.
    assert D(r["value"]) == 1360
    assert float(r["return"]) == pytest.approx(1360 / 1250 - 1)
    sid = before["holdings"][0]["security"]["id"]
    scenario_result = db_client.post(url, json={**period, "exclude_security_ids": [sid]}).json()
    assert D(scenario_result["scenario"]["value"]) == 1250
    assert D(scenario_result["scenario"]["return"]) == 0
    assert ledger(db_client, aid) == before
    data["AAA"].splits.add(DAYS[2])
    assert db_client.post(url, json=period).status_code == 422
    data["AAA"].splits.clear()
    del data["AAA"].close[DAYS[2]]
    assert db_client.post(url, json=period).status_code == 422
    assert ledger(db_client, aid) == before


def test_recorded_baseline_preserves_fifo_lots_across_partial_sales(db_client, portfolio):
    aid, _ = portfolio
    cash(db_client, aid, amount="1000", day="2026-01-02")
    trade(db_client, aid, quantity="5", price="200", ticker="AAA", exchange="NYSE")
    trade(
        db_client,
        aid,
        "sell",
        "5",
        "110",
        ticker="AAA",
        exchange="NYSE",
        effective_date="2026-01-05",
    )
    before = ledger(db_client, aid)
    result = db_client.post(
        f"/api/accounts/{aid}/performance",
        json={"start": "2026-01-05", "end": "2026-01-06", "baseline": "recorded"},
    ).json()
    # Five shares from the original $100 lot remain, along with all five $200 shares.
    assert D(result["holdings"][0]["basis"]) == 1500
    assert D(result["holdings"][0]["unrealized_pnl"]) == -290
    assert ledger(db_client, aid) == before


def test_dated_receipt_does_not_cross_earlier_split_or_inflate_return(db_client, portfolio):
    aid, data = portfolio
    # Finish the old episode, then receive new shares after a corporate action.
    assert (
        trade(
            db_client,
            aid,
            "sell",
            "10",
            "100",
            effective_date="2026-01-02",
            ticker="AAA",
            exchange="NYSE",
        ).status_code
        == 201
    )
    data["AAA"].splits = {DAYS[1]}
    response = trade(
        db_client,
        aid,
        "transfer_in",
        "2",
        effective_date="2026-01-06",
        cost_basis="50",
        ticker="AAA",
        exchange="NYSE",
    )
    assert response.status_code == 201, response.text
    state = ledger(db_client, aid)
    assert D(state["balance"]) == 1000
    assert D(state["holdings"][0]["cost_basis"]) == 50
    result = report(db_client, aid)
    assert result.status_code == 200, result.text
    assert D(result.json()["value"]) == 1242
    assert D(result.json()["return"]) == 0  # Received market value is an external flow.
    scenario = db_client.post(
        f"/api/accounts/{aid}/performance",
        json={
            "start": "2026-01-02",
            "end": "2026-01-06",
            "exclude_security_ids": [state["holdings"][0]["security"]["id"]],
        },
    ).json()
    assert D(scenario["scenario"]["return"]) == 0


def test_cash_expenses_reduce_return_while_withdrawals_do_not(db_client, portfolio):
    aid, data = portfolio
    # Flat prices isolate the treatment of funding, fees and account income.
    data["AAA"].close = dict.fromkeys(DAYS, D("100"))
    assert cash(db_client, aid, "deposit", "200", day="2026-01-05").status_code == 201
    assert cash(db_client, aid, "income", "20", day="2026-01-06").status_code == 201
    expense = cash(db_client, aid, "expense", "10", day="2026-01-06")
    assert expense.status_code == 201
    assert cash(db_client, aid, "withdrawal", "100", day="2026-01-06").status_code == 201
    result = report(db_client, aid).json()
    assert D(result["cash"]) == 110
    assert float(result["return"]) == pytest.approx(10 / 1200)
    before = ledger(db_client, aid)
    assert cash(db_client, aid, "expense", "111", day="2026-01-06").status_code == 409
    assert ledger(db_client, aid) == before


@pytest.mark.parametrize("baseline", ["history", "recorded"])
def test_inferred_funding_withholds_returns_and_scenarios_until_reconciled(
    db_client, portfolio, database, baseline
):
    from uuid import UUID

    from sqlalchemy.orm import Session

    from investor_platform.domain import FundingStatus
    from investor_platform.models import Account

    aid, _ = portfolio
    # Legacy imports have no status field, so they must fail closed too.
    with Session(database) as session:
        session.get(Account, UUID(aid)).reconstruction = {"opening_cash": "1000"}
        session.commit()
    before = ledger(db_client, aid)
    sid = before["holdings"][0]["security"]["id"]
    result = scenario(db_client, aid, [sid], baseline=baseline).json()
    assert result["funding_status"] == FundingStatus.INFERRED
    assert result["return"] is None
    assert result["cagr"]["portfolio"] is None
    assert result["excess_spy"] is None and result["excess_qqq"] is None
    assert all(p["portfolio"] is None for p in result["series"])
    assert result["scenario"] is None
    assert "cash history" in result["scenario_error"]
    assert result["SPY"] == "0.02" and result["QQQ"] == "0.04"
    assert ledger(db_client, aid) == before
    with Session(database) as session:
        session.get(Account, UUID(aid)).reconstruction = {
            "funding_status": FundingStatus.RECONCILED,
        }
        session.commit()
    result = scenario(db_client, aid, [sid], baseline=baseline).json()
    assert result["warnings"] == []
    assert D(result["return"]) == D(".21")
    assert D(result["scenario"]["return"]) == 0
