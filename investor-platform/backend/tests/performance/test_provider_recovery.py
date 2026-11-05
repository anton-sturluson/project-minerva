import io
import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from helpers import DAYS, cash, report, trade

from investor_platform.market_data import tiingo
from investor_platform.market_data import yahoo as market_yahoo


@pytest.mark.parametrize("stock_currency", [None, "CAD"])
def test_performance_recovers_empty_provider_history_without_accepting_foreign_prices(
    db_client, monkeypatch, stock_currency
):
    monkeypatch.setenv("TIINGO_API_KEY", "synthetic-token")
    account = db_client.post(
        "/api/accounts", json={"name": "Provider recovery fixture", "base_currency": "USD"}
    ).json()["id"]
    assert cash(db_client, account, "opening_cash", "1000", day="2026-01-02").status_code == 201
    assert (
        trade(
            db_client, account, quantity="10", price="100", ticker="AAA", exchange="NYSE"
        ).status_code
        == 201
    )

    def yahoo_response(request, timeout):
        stock = "/chart/AAA?" in request.full_url
        stamps = [
            int(datetime(day.year, day.month, day.day, 20, tzinfo=UTC).timestamp()) for day in DAYS
        ]
        result = {
            "meta": {
                "currency": stock_currency if stock else "USD",
                "exchangeName": "NYQ" if stock else "PCX",
                "instrumentType": "EQUITY" if stock else "ETF",
                "exchangeTimezoneName": "America/New_York",
            },
            "timestamp": [] if stock else stamps,
            "indicators": {
                "quote": [{"close": [] if stock else [100, 100, 101]}],
                "adjclose": [{"adjclose": [] if stock else [100, 101, 102]}],
            },
        }
        return io.BytesIO(json.dumps({"chart": {"result": [result]}}).encode())

    def tiingo_response(path, key):
        if "/prices?" not in path:
            return {"ticker": "AAA", "exchangeCode": "NYSE", "currency": "USD"}
        return [
            {
                "date": day.isoformat(),
                "close": price,
                "adjClose": price,
                "divCash": "0",
                "splitFactor": "1",
            }
            for day, price in zip(DAYS, ["100", "110", "121"], strict=True)
        ]

    monkeypatch.setattr(market_yahoo, "urlopen", yahoo_response)
    monkeypatch.setattr(tiingo, "get", tiingo_response)
    response = report(db_client, account)
    if stock_currency is not None:
        assert response.status_code == 422
        assert "AAA" in response.json()["detail"]
        assert "CAD" in response.json()["detail"]
    else:
        assert response.status_code == 200, response.text
        result = response.json()
        assert Decimal(result["value"]) == Decimal("1210")
        assert Decimal(result["return"]) == Decimal(".21")
        assert Decimal(result["SPY"]) == Decimal(".02")
        assert "Tiingo daily history" in result["source"]
