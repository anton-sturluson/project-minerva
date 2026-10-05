from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from investor_platform import market, tiingo
from investor_platform.db import LOCAL_WORKSPACE
from investor_platform.models import MarketCache

START, END = date(2020, 1, 2), date(2020, 1, 3)


def sample():
    return {
        "meta": {"ticker": "AAA", "exchangeCode": "NYSE"},
        "rows": [
            {
                "date": "2020-01-02T00:00:00.000Z",
                "close": "2",
                "adjClose": "20",
                "divCash": "0.01",
                "splitFactor": "1",
            },
            {
                "date": "2020-01-03T00:00:00.000Z",
                "close": "21",
                "adjClose": "21",
                "divCash": "0",
                "splitFactor": "0.1",
            },
        ],
    }


def test_tiingo_keeps_actual_share_units_and_actions():
    h = tiingo.parse_stock(sample(), "AAA")
    assert h.close[START] == Decimal(2)  # Not the reverse-split-adjusted 20.
    assert h.adjusted[START] == Decimal(20)
    assert h.dividends[START] == Decimal(".01")
    assert h.splits == {END}
    assert h.source == "Tiingo daily history"
    with pytest.raises(ValueError, match="identity"):
        tiingo.parse_stock(sample(), "OTHER")


def test_cache_covers_retries_expands_ranges_and_rejects_bad_refresh(database, monkeypatch):
    monkeypatch.setenv("TIINGO_API_KEY", "synthetic-token")
    requests = []
    body = sample()

    def fetch(path, key):
        requests.append(path)
        assert key == "synthetic-token"
        return body["rows"] if "/prices?" in path else body["meta"]

    monkeypatch.setattr(tiingo, "get", fetch)
    assert tiingo.payload(database, LOCAL_WORKSPACE, "AAA", START, END) == body
    tiingo.payload(database, LOCAL_WORKSPACE, "AAA", START, START)
    assert len(requests) == 2
    assert all("token" not in path for path in requests)
    tiingo.payload(database, LOCAL_WORKSPACE, "AAA", START - timedelta(days=1), END)
    assert len(requests) == 4
    with Session(database) as session:
        assert session.scalar(select(func.count()).select_from(MarketCache)) == 1
    body["rows"] = []
    with pytest.raises(ValueError, match="No Tiingo"):
        tiingo.payload(database, LOCAL_WORKSPACE, "AAA", START, END + timedelta(days=1))
    assert tiingo.payload(database, LOCAL_WORKSPACE, "AAA", START, END)["rows"]


def test_historical_exchange_exception_requires_dated_evidence(monkeypatch):
    body = sample()
    body["meta"]["exchangeCode"] = "PINK"
    monkeypatch.setattr(tiingo, "payload", lambda *args: body)
    security = SimpleNamespace(
        ticker="AAA", exchange="NASDAQ", currency="USD", market_identity=None
    )
    with pytest.raises(ValueError, match="verify historical"):
        tiingo.stock_history(security, START, END, None, LOCAL_WORKSPACE)
    security.market_identity = {
        "tiingo": {
            "symbol": "AAA",
            "exchange": "NASDAQ",
            "from": START.isoformat(),
            "through": END.isoformat(),
            "source": "https://example.org/listing",
        }
    }
    assert tiingo.stock_history(security, START, END, None, LOCAL_WORKSPACE).exchange == "NMS"
    with pytest.raises(ValueError, match="verify historical"):
        tiingo.stock_history(security, START, END + timedelta(days=1), None, LOCAL_WORKSPACE)


def test_fx_uses_same_date_reciprocal_without_filling_missing_days():
    h = tiingo.parse_fx(
        {"rows": [{"date": "2020-01-02T00:00:00.000Z", "ticker": "usdcad", "close": "1.25"}]},
        "usdcad",
    )
    assert h.close == {START: Decimal(".8")}
    with pytest.raises(ValueError, match="pair"):
        tiingo.parse_fx(
            {"rows": [{"date": "2020-01-02", "ticker": "usdaud", "close": "1"}]}, "usdcad"
        )


def test_yahoo_failure_falls_back_only_for_the_required_holding_window(monkeypatch):
    monkeypatch.setenv("TIINGO_API_KEY", "synthetic-token")

    def yahoo(symbol, first, last):
        if symbol == "AAA":
            raise OSError("delisted")
        assert (first, last) == (START - market.MAX_CLOSE_AGE, END)
        return market.History({START: Decimal(1)}, {})

    calls = []

    def fallback(security, first, last, engine, workspace_id):
        calls.append((first, last))
        return tiingo.parse_stock(sample(), "AAA")

    monkeypatch.setattr(market, "history", yahoo)
    monkeypatch.setattr(tiingo, "stock_history", fallback)
    result = market.security_histories(
        [SimpleNamespace(ticker="AAA", exchange="NYSE", currency="USD")],
        START,
        END,
        engine=object(),
        workspace_id=LOCAL_WORKSPACE,
        windows={"AAA": (START, START)},
    )
    assert calls == [(START, START)]
    assert result["AAA"].source == "Tiingo daily history"


def test_pln_valuation_uses_inverse_usd_pair(monkeypatch):
    calls = []

    def payload(engine, workspace, symbol, start, end, *, fx):
        calls.append((symbol, fx))
        return {"rows": [{"date": "2020-01-02", "ticker": "usdpln", "close": "4"}]}

    monkeypatch.setattr(tiingo, "payload", payload)
    result = tiingo.fx_history("PLN", START, END, None, LOCAL_WORKSPACE)
    assert calls == [("usdpln", True)]
    assert result.close[START] == Decimal(".25")
