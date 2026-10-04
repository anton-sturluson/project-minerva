import io
import json
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from investor_platform import market


def test_provider_dates_adjustments_and_future_split(monkeypatch):
    def stamp(day):
        return int(datetime(2026, 1, day, 14, 30, tzinfo=UTC).timestamp())

    payload = {
        "chart": {
            "result": [
                {
                    "meta": {
                        "currency": "USD",
                        "exchangeName": "NYQ",
                        "instrumentType": "EQUITY",
                        "exchangeTimezoneName": "America/New_York",
                    },
                    "timestamp": [stamp(2), stamp(5), stamp(6)],
                    "indicators": {
                        "quote": [{"close": [50, 55, None]}],
                        "adjclose": [{"adjclose": [49, 54, None]}],
                    },
                    "events": {
                        "splits": {"one": {"date": stamp(7), "numerator": 2, "denominator": 1}},
                        "dividends": {"one": {"date": stamp(5), "amount": 1}},
                    },
                }
            ]
        }
    }
    monkeypatch.setattr(
        market, "urlopen", lambda request, timeout: io.BytesIO(json.dumps(payload).encode())
    )
    h = market.history("AAA", date(2026, 1, 2), date(2026, 1, 5))
    assert h.close == {date(2026, 1, 2): Decimal(100), date(2026, 1, 5): Decimal(110)}
    assert h.adjusted[date(2026, 1, 2)] == 49
    assert date(2026, 1, 7) in h.splits
    assert h.dividends[date(2026, 1, 5)] == 2
    payload["chart"]["result"][0]["meta"]["currency"] = "CAD"
    with pytest.raises(ValueError, match="currency"):
        market.history("AAA", date(2026, 1, 2), date(2026, 1, 5))


def test_foreign_holiday_keeps_local_close_but_updates_fx_without_lookahead():
    from decimal import Decimal as D

    from investor_platform.market import History, usd_history

    days = [date(2026, 1, d) for d in [2, 5, 6, 7, 12]]
    local = History(
        {days[0]: D(10), days[2]: D(20)},
        {days[0]: D(9), days[2]: D(19)},
        dividends={days[2]: D(1)},
        exchange="TOR",
    )
    fx = History(dict(zip(days, map(D, [".7", ".8", ".9", ".95", "1"]))), {})
    usd = usd_history(local, fx)
    assert usd.close == dict(zip(days[:4], map(D, ["7", "8", "18", "19"])))
    assert usd.dividends == {days[2]: D(".9")}
    assert usd.adjusted[days[1]] == D("7.2")
    local.splits.add(days[1])
    assert days[1] not in usd_history(local, fx).close
    del fx.close[days[2]]
    with pytest.raises(ValueError, match="exchange rate"):
        usd_history(local, fx)


def test_provisional_import_still_checks_a_confirmed_exchange():
    from types import SimpleNamespace

    security = SimpleNamespace(ticker="AAA", exchange="NYSE", currency="USD")
    with pytest.raises(ValueError, match="listing does not match"):
        market.verify_exchange(security, market.History({}, {}, exchange="NMS"), provisional=True)
