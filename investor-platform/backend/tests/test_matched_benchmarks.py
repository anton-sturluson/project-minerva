from datetime import date
from decimal import Decimal as D

import pytest
from helpers import DAYS, cash, ledger, stock_report, trade


def matched(client, aid, **extra):
    response = stock_report(client, aid, benchmark_mode="matched", **extra)
    assert response.status_code == 200, response.text
    return response.json()


def test_unequal_deployments_and_fifo_partial_exits_match_both_indexes(db_client, portfolio):
    aid, _ = portfolio
    assert cash(db_client, aid, amount="2000", day=str(DAYS[1])).status_code == 201
    assert (
        trade(
            db_client,
            aid,
            quantity="20",
            ticker="AAA",
            exchange="NYSE",
            effective_date=str(DAYS[1]),
        ).status_code
        == 201
    )
    assert (
        trade(
            db_client,
            aid,
            "sell",
            "15",
            "120",
            ticker="AAA",
            exchange="NYSE",
            effective_date=str(DAYS[2]),
        ).status_code
        == 201
    )
    before = ledger(db_client, aid)
    result = matched(db_client, aid)
    for symbol, middle, end in [("SPY", D(101), D(102)), ("QQQ", D(102), D(104))]:
        # Initial $1000, later $2000. Exit the first ten shares plus 5/20 of lot two.
        units = D(10) + D(2000) / middle
        remaining = D(1500) / middle * end
        proceeds = (D(10) + D(500) / middle) * end
        expected_return = (D(10) * middle + 2000) / 3000 * end / middle - 1
        assert float(result[symbol]) == pytest.approx(float(expected_return))
        metric = result["matched_benchmarks"][symbol]
        assert float(metric["value"]) == pytest.approx(float(remaining))
        assert float(metric["proceeds"]) == pytest.approx(float(proceeds))
        assert float(metric["gain"]) == pytest.approx(float(units * end - 3000))
        assert result["cagr"][symbol] is None  # Short periods are not annualized.
    assert result["benchmark_mode"] == "matched"
    assert ledger(db_client, aid) == before
    ordinary = stock_report(db_client, aid).json()
    assert result["return"] == ordinary["return"]
    assert D(ordinary["SPY"]) == D(".02")
    assert D(ordinary["QQQ"]) == D(".04")
    assert ordinary["matched_benchmarks"] is None


def test_flat_intervals_skip_index_gains_and_reentry_uses_new_dollars(db_client, portfolio):
    aid, data = portfolio
    assert (
        trade(
            db_client,
            aid,
            "sell",
            ticker="AAA",
            exchange="NYSE",
            effective_date=str(DAYS[1]),
        ).status_code
        == 201
    )
    flat = matched(db_client, aid)
    assert D(flat["SPY"]) == D(".01")
    assert D(flat["QQQ"]) == D(".02")
    assert D(flat["matched_benchmarks"]["SPY"]["value"]) == 0
    assert D(flat["matched_benchmarks"]["SPY"]["gain"]) == 10
    later, last = date(2026, 1, 7), date(2026, 1, 8)
    for history in data.values():
        history.close[later] = history.adjusted[later] = D(120)
        history.close[last] = history.adjusted[last] = D(126)
    assert (
        trade(
            db_client,
            aid,
            quantity="5",
            ticker="AAA",
            exchange="NYSE",
            effective_date=str(later),
        ).status_code
        == 201
    )
    result = matched(db_client, aid, end=str(last))
    assert D(result["SPY"]) == D(".0605")
    assert D(result["matched_benchmarks"]["SPY"]["gain"]) == 35
    assert D(result["matched_benchmarks"]["SPY"]["value"]) == 525


def test_recorded_baseline_uses_opening_market_value_not_cost(db_client, portfolio):
    aid, _ = portfolio
    result = matched(db_client, aid, start=str(DAYS[1]), baseline="recorded")
    assert result["series"][0]["SPY"] == "0"
    assert float(result["matched_benchmarks"]["SPY"]["value"]) == pytest.approx(1100 * 102 / 101)
    assert float(result["matched_benchmarks"]["SPY"]["gain"]) == pytest.approx(1100 / 101)
    # Full replay preserves actual past purchase capital before rebasing the selected period.
    historical = matched(db_client, aid, start=str(DAYS[1]))
    assert D(historical["matched_benchmarks"]["SPY"]["value"]) == 1020
    assert D(historical["matched_benchmarks"]["SPY"]["gain"]) == 10


def test_in_kind_receipts_use_close_value_without_inventing_cost(db_client, portfolio):
    aid, _ = portfolio
    assert (
        trade(
            db_client,
            aid,
            "transfer_in",
            "2",
            ticker="AAA",
            exchange="NYSE",
            effective_date=str(DAYS[1]),
            cost_basis=None,
        ).status_code
        == 201
    )
    result = matched(db_client, aid)
    assert float(result["SPY"]) == pytest.approx(0.02)
    assert float(result["matched_benchmarks"]["SPY"]["gain"]) == pytest.approx(20 + 220 / 101)


def test_weekend_purchase_maps_to_next_close_and_includes_fees(db_client, portfolio):
    aid, _ = portfolio
    assert cash(db_client, aid, amount="501", day="2026-01-03").status_code == 201
    assert (
        trade(
            db_client,
            aid,
            quantity="5",
            ticker="AAA",
            exchange="NYSE",
            fees="1",
            effective_date="2026-01-03",
        ).status_code
        == 201
    )
    result = matched(db_client, aid)
    assert float(result["matched_benchmarks"]["SPY"]["gain"]) == pytest.approx(20 + 501 / 101)


def test_stock_exclusion_keeps_original_matched_index_deployments(db_client, portfolio):
    aid, _ = portfolio
    assert cash(db_client, aid, amount="500", day=str(DAYS[1])).status_code == 201
    assert (
        trade(
            db_client,
            aid,
            quantity="5",
            ticker="SPY",
            exchange="ARCA",
            effective_date=str(DAYS[1]),
        ).status_code
        == 201
    )
    sid = ledger(db_client, aid)["holdings"][0]["security"]["id"]
    result = matched(db_client, aid, exclude_security_ids=[sid])
    assert result["scenario_error"] is None
    assert result["scenario"]["SPY"] == result["SPY"]
    assert result["scenario"]["matched_benchmarks"] == result["matched_benchmarks"]
    assert [p["QQQ"] for p in result["scenario"]["series"]] == [p["QQQ"] for p in result["series"]]


def test_missing_price_fails_and_recovers_and_mode_is_validated(
    db_client, portfolio, expire_prices
):
    aid, data = portfolio
    original = data["AAA"].close.pop(DAYS[1])
    assert stock_report(db_client, aid, benchmark_mode="matched").status_code == 422
    data["AAA"].close[DAYS[1]] = original
    expire_prices()
    assert matched(db_client, aid)["return"] is not None
    assert stock_report(db_client, aid, benchmark_mode="unknown").status_code == 422


def test_displayed_cash_only_days_before_first_deployment_stay_flat(db_client, portfolio):
    aid = db_client.post(
        "/api/accounts", json={"name": "Later stock purchase", "base_currency": "USD"}
    ).json()["id"]
    assert cash(db_client, aid, "opening_cash", "1000", day=str(DAYS[0])).status_code == 201
    assert (
        trade(
            db_client,
            aid,
            ticker="AAA",
            exchange="NYSE",
            effective_date=str(DAYS[1]),
        ).status_code
        == 201
    )
    result = matched(db_client, aid)
    assert D(result["series"][0]["SPY"]) == 0
    assert D(result["series"][1]["SPY"]) == 0
    assert float(result["SPY"]) == pytest.approx(102 / 101 - 1)
    assert float(result["matched_benchmarks"]["SPY"]["gain"]) == pytest.approx(1000 / 101)


def test_matched_cagr_and_excess_returns_use_selected_benchmark_series(db_client, portfolio):
    _, data = portfolio
    start = date(2024, 1, 2)
    for history in data.values():
        history.close[start] = history.adjusted[start] = D(100)
    aid = db_client.post(
        "/api/accounts", json={"name": "Long matched period", "base_currency": "USD"}
    ).json()["id"]
    assert cash(db_client, aid, "opening_cash", "1000", day=str(start)).status_code == 201
    assert (
        trade(
            db_client,
            aid,
            ticker="AAA",
            exchange="NYSE",
            effective_date=str(start),
        ).status_code
        == 201
    )
    result = matched(db_client, aid, start=str(start))
    elapsed = (DAYS[-1] - start).days
    for symbol in ("SPY", "QQQ"):
        assert float(result["cagr"][symbol]) == pytest.approx(
            (1 + float(result[symbol])) ** (365.25 / elapsed) - 1
        )
    assert float(result["excess_spy"]) == pytest.approx(
        float(result["return"]) - float(result["SPY"])
    )


def test_benchmark_dividends_reinvest_even_when_raw_prices_are_flat(db_client, portfolio):
    aid, data = portfolio
    # Two $5 distributions on a flat $100 fund compound to $102.50 of gain,
    # rather than a zero price return or $100 of unreinvested distributions.
    data["SPY"].close = dict.fromkeys(DAYS, D(100))
    data["SPY"].adjusted = dict(zip(DAYS, map(D, ["100", "105", "110.25"])))
    data["SPY"].dividends = {DAYS[1]: D(5), DAYS[2]: D(5)}
    data["QQQ"].close = dict(zip(DAYS, map(D, ["100", "110", "120"])))
    data["QQQ"].adjusted = dict(zip(DAYS, map(D, ["100", "110", "125"])))
    data["QQQ"].dividends = {DAYS[2]: D(5)}
    result = matched(db_client, aid)
    assert D(result["SPY"]) == D(".1025")
    assert D(result["matched_benchmarks"]["SPY"]["gain"]) == D("102.50")
    assert D(result["QQQ"]) == D(".25")
    assert D(result["matched_benchmarks"]["QQQ"]["gain"]) == D(250)
    assert D(result["return"]) == D(".21")
