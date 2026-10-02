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
