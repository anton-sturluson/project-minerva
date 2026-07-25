"""Tests for minerva.prices — 52-week price position tracking.

Network is isolated behind an injectable fetcher, so no HTTP mocking.
DB tests use a real temporary sqlite file built from the module's own schema.
"""

from __future__ import annotations

import sqlite3
import time
from datetime import UTC, date, datetime
from pathlib import Path

from minerva.prices import (
    PriceRow,
    RateLimiter,
    daily_change_pct,
    download_market_data,
    ensure_schema,
    market_movement_from_chart,
    range_pct,
    read_positions,
    refresh_prices,
    tracked_companies,
    upsert_prices,
    yahoo_symbol,
)


def _row(ticker: str, current: float, low: float, high: float, as_of: str = "2026-07-01") -> PriceRow:
    return PriceRow(ticker=ticker, as_of=as_of, current=current, wk52_low=low, wk52_high=high, currency="USD")


YAHOO_DAILY_RESPONSE = {
    "chart": {
        "result": [
            {
                "meta": {
                    "currency": "USD",
                    "exchangeTimezoneName": "America/New_York",
                    "fiftyTwoWeekLow": 80.0,
                    "fiftyTwoWeekHigh": 130.0,
                    "currentTradingPeriod": {"regular": {"end": 1783368000}},
                },
                "timestamp": [1782912600, 1782999000, 1783344600],
                "indicators": {"quote": [{"close": [100.0, 110.0, 121.0]}]},
            }
        ],
        "error": None,
    }
}


class TestRangePct:
    def test_on_low_is_zero(self):
        assert range_pct(_row("A", current=100, low=100, high=200)) == 0.0

    def test_on_high_is_one(self):
        assert range_pct(_row("A", current=200, low=100, high=200)) == 1.0

    def test_midpoint_is_half(self):
        assert range_pct(_row("A", current=150, low=100, high=200)) == 0.5

    def test_high_equals_low_returns_none(self):
        assert range_pct(_row("A", current=100, low=100, high=100)) is None

    def test_missing_inputs_return_none(self):
        assert range_pct(PriceRow("A", "2026-07-01", None, 100, 200)) is None


class TestYahooSymbol:
    def test_us_ticker_is_bare(self):
        assert yahoo_symbol("AAPL", None) == "AAPL"
        assert yahoo_symbol("AAPL", "") == "AAPL"

    def test_exchange_suffixes(self):
        assert yahoo_symbol("CSU", "TSX") == "CSU.TO"
        assert yahoo_symbol("TOI", "TSXV") == "TOI.V"
        assert yahoo_symbol("XRO", "ASX") == "XRO.AX"
        assert yahoo_symbol("REL", "LSE") == "REL.L"
        assert yahoo_symbol("4478", "TSE") == "4478.T"

    def test_already_suffixed_passes_through(self):
        assert yahoo_symbol("AMS.MC", "BME") == "AMS.MC"
        assert yahoo_symbol("HEXA-B.ST", "STO") == "HEXA-B.ST"

    def test_unknown_exchange_falls_back_to_bare(self):
        assert yahoo_symbol("FOO", "NOPE") == "FOO"


class TestMarketMovement:
    def test_uses_actual_sessions_and_excludes_an_incomplete_current_day(self):
        weekend = market_movement_from_chart(
            "AAPL",
            date(2026, 7, 5),
            YAHOO_DAILY_RESPONSE,
            now=datetime(2026, 7, 6, 14, tzinfo=UTC),
        )
        current_session = market_movement_from_chart(
            "AAPL",
            date(2026, 7, 6),
            YAHOO_DAILY_RESPONSE,
            now=datetime(2026, 7, 6, 14, tzinfo=UTC),
        )

        assert (weekend.as_of, weekend.current, weekend.previous_close) == (
            "2026-07-02",
            110.0,
            100.0,
        )
        assert current_session.as_of == "2026-07-02"

    def test_percentage_math_is_stored_in_percentage_points(self):
        assert daily_change_pct(97.5, 100.0) == -2.5
        assert daily_change_pct(10.0, 0.0) is None


class TestSchemaAndPersistence:
    def test_ensure_schema_creates_table_and_view(self, tmp_path: Path):
        db = tmp_path / "test.db"
        ensure_schema(db)
        with sqlite3.connect(db) as conn:
            objects = {
                name for (name,) in conn.execute(
                    "SELECT name FROM sqlite_master WHERE name IN ('prices','price_position')"
                )
            }
        assert objects == {"prices", "price_position"}

    def test_migrates_legacy_schema_and_preserves_price_position(self, tmp_path: Path):
        db = tmp_path / "legacy.db"
        with sqlite3.connect(db) as conn:
            conn.executescript(
                """
                CREATE TABLE prices (
                    id INTEGER PRIMARY KEY, ticker TEXT NOT NULL, as_of TEXT NOT NULL,
                    current REAL, wk52_low REAL, wk52_high REAL, currency TEXT,
                    source TEXT NOT NULL DEFAULT 'yahoo', fetched_at TEXT NOT NULL,
                    UNIQUE (ticker, as_of)
                );
                CREATE VIEW price_position AS
                SELECT ticker, as_of, current, wk52_low, wk52_high, currency,
                       ROUND((current - wk52_low) / NULLIF(wk52_high - wk52_low, 0), 4) AS range_pct
                FROM prices;
                INSERT INTO prices
                    (ticker, as_of, current, wk52_low, wk52_high, currency, fetched_at)
                VALUES ('AAPL', '2026-07-01', 150, 100, 200, 'USD', datetime('now'));
                """
            )

        ensure_schema(db)
        ensure_schema(db)

        with sqlite3.connect(db) as conn:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(prices)")}
            view_columns = [
                row[1] for row in conn.execute("PRAGMA table_info(price_position)")
            ]
            position = conn.execute(
                "SELECT range_pct, previous_close, instrument_type FROM price_position"
            ).fetchone()
        assert {"previous_close", "change_pct", "instrument_type"} <= columns
        assert view_columns[:7] == [
            "ticker", "as_of", "current", "wk52_low", "wk52_high", "currency", "range_pct"
        ]
        assert position == (0.5, None, "security")

    def test_upsert_then_read(self, tmp_path: Path):
        db = tmp_path / "test.db"
        ensure_schema(db)
        upsert_prices(db, [_row("AAPL", current=150, low=100, high=200)])
        positions = read_positions(db)
        assert len(positions) == 1
        assert positions[0]["ticker"] == "AAPL"
        assert positions[0]["range_pct"] == 0.5
        assert positions[0]["currency"] == "USD"

    def test_upsert_is_idempotent_per_day(self, tmp_path: Path):
        db = tmp_path / "test.db"
        ensure_schema(db)
        upsert_prices(db, [_row("AAPL", current=150, low=100, high=200)])
        upsert_prices(db, [_row("AAPL", current=120, low=100, high=200)])
        positions = read_positions(db)
        assert len(positions) == 1
        assert positions[0]["current"] == 120

    def test_read_positions_sorted_by_range_pct(self, tmp_path: Path):
        db = tmp_path / "test.db"
        ensure_schema(db)
        upsert_prices(db, [
            _row("HIGH", current=190, low=100, high=200),
            _row("LOW", current=110, low=100, high=200),
            _row("MID", current=150, low=100, high=200),
        ])
        assert [p["ticker"] for p in read_positions(db)] == ["LOW", "MID", "HIGH"]

    def test_read_positions_filters_by_ticker(self, tmp_path: Path):
        db = tmp_path / "test.db"
        ensure_schema(db)
        upsert_prices(db, [
            _row("AAPL", current=150, low=100, high=200),
            _row("MSFT", current=180, low=100, high=200),
        ])
        assert [p["ticker"] for p in read_positions(db, tickers=["AAPL"])] == ["AAPL"]


class TestTrackedCompanies:
    def test_returns_ticker_and_exchange(self, tmp_path: Path):
        db = tmp_path / "test.db"
        with sqlite3.connect(db) as conn:
            conn.execute("CREATE TABLE companies (id INTEGER PRIMARY KEY, ticker TEXT, name TEXT, exchange TEXT)")
            conn.executemany(
                "INSERT INTO companies (ticker, name, exchange) VALUES (?, ?, ?)",
                [
                    ("AAPL", "Apple", None),
                    ("CSU", "Constellation", "TSX"),
                    (None, "Private Co", None),  # null ticker excluded
                    ("", "Blank Co", "TSX"),     # empty ticker excluded
                ],
            )
            conn.commit()
        assert tracked_companies(db) == [("AAPL", None), ("CSU", "TSX")]


class TestRefreshPrices:
    def test_download_market_data_is_idempotent_and_reports_errors(
        self, tmp_path: Path
    ):
        db = tmp_path / "test.db"

        def fake_fetcher(ticker: str, *, target_date: date, **_kw) -> PriceRow:
            if ticker == "BAD":
                raise ValueError("no chart data")
            return market_movement_from_chart(
                ticker,
                target_date,
                YAHOO_DAILY_RESPONSE,
                now=datetime(2026, 7, 6, 14, tzinfo=UTC),
            )

        instruments = [("AAPL", None, "security"), ("BAD", None, "security")]
        first = download_market_data(
            db, instruments, date(2026, 7, 5), fetcher=fake_fetcher
        )
        second = download_market_data(
            db, instruments, date(2026, 7, 5), fetcher=fake_fetcher
        )
        # The legacy portfolio refresh path must not erase stored movement fields.
        upsert_prices(db, [_row("AAPL", 110, 80, 130, as_of="2026-07-02")])

        with sqlite3.connect(db) as conn:
            rows = conn.execute(
                "SELECT ticker, as_of, current, previous_close, change_pct FROM prices"
            ).fetchall()
        assert rows == [("AAPL", "2026-07-02", 110.0, 100.0, 10.0)]
        assert (
            first
            == second
            == {
                "requested": 2,
                "written": 1,
                "trading_dates": ["2026-07-02"],
                "errors": [{"symbol": "BAD", "error": "no chart data"}],
            }
        )

    def test_refresh_persists_all_with_fake_fetcher(self, tmp_path: Path):
        db = tmp_path / "test.db"
        ensure_schema(db)

        def fake_fetcher(ticker: str, **_kw) -> PriceRow:
            table = {"AAPL": (150, 100, 200), "CSU": (180, 100, 200), "TOI": (120, 100, 200)}
            cur, low, high = table[ticker]
            return _row(ticker, current=cur, low=low, high=high)

        result = refresh_prices(db, [("AAPL", None), ("CSU", "TSX"), ("TOI", "TSXV")], fetcher=fake_fetcher)
        assert result["fetched"] == 3
        assert result["errors"] == []
        assert len(read_positions(db)) == 3

    def test_refresh_records_per_ticker_errors_and_continues(self, tmp_path: Path):
        db = tmp_path / "test.db"
        ensure_schema(db)

        def flaky_fetcher(ticker: str, **_kw) -> PriceRow:
            if ticker == "BAD":
                raise ValueError("no chart data")
            return _row(ticker, current=150, low=100, high=200)

        result = refresh_prices(db, [("AAPL", None), ("BAD", None), ("MSFT", None)], fetcher=flaky_fetcher)
        assert result["fetched"] == 2
        assert [e["ticker"] for e in result["errors"]] == ["BAD"]
        assert {p["ticker"] for p in read_positions(db)} == {"AAPL", "MSFT"}


class TestRateLimiter:
    def test_spacing_enforced(self):
        limiter = RateLimiter(min_interval=0.05)
        start = time.monotonic()
        limiter.acquire()
        limiter.acquire()
        assert time.monotonic() - start >= 0.05
