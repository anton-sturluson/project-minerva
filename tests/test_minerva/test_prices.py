"""Tests for minerva.prices — 52-week price position tracking.

Network is isolated behind an injectable fetcher, so no requests mocking.
DB tests use a real temporary sqlite file built from the module's own schema.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest

from minerva.prices import (
    PriceRow,
    RateLimiter,
    ensure_schema,
    range_pct,
    read_positions,
    refresh_prices,
    tracked_tickers,
    upsert_prices,
)


def _row(ticker: str, current: float, low: float, high: float, as_of: str = "2026-07-01") -> PriceRow:
    return PriceRow(
        ticker=ticker,
        as_of=as_of,
        current=current,
        wk52_low=low,
        wk52_high=high,
        low_date="2025-06-30",
        high_date="2026-06-08",
    )


class TestRangePct:
    def test_on_low_is_zero(self):
        assert range_pct(_row("A", current=100, low=100, high=200)) == 0.0

    def test_on_high_is_one(self):
        assert range_pct(_row("A", current=200, low=100, high=200)) == 1.0

    def test_midpoint_is_half(self):
        assert range_pct(_row("A", current=150, low=100, high=200)) == 0.5

    def test_high_equals_low_returns_none(self):
        # No range: undefined position, must not divide by zero.
        assert range_pct(_row("A", current=100, low=100, high=100)) is None

    def test_missing_inputs_return_none(self):
        assert range_pct(PriceRow("A", "2026-07-01", None, 100, 200)) is None


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

    def test_ensure_schema_is_idempotent(self, tmp_path: Path):
        db = tmp_path / "test.db"
        ensure_schema(db)
        ensure_schema(db)  # second call must not raise

    def test_upsert_then_read(self, tmp_path: Path):
        db = tmp_path / "test.db"
        ensure_schema(db)
        upsert_prices(db, [_row("AAPL", current=150, low=100, high=200)])
        positions = read_positions(db)
        assert len(positions) == 1
        assert positions[0]["ticker"] == "AAPL"
        assert positions[0]["range_pct"] == 0.5

    def test_upsert_is_idempotent_per_day(self, tmp_path: Path):
        db = tmp_path / "test.db"
        ensure_schema(db)
        upsert_prices(db, [_row("AAPL", current=150, low=100, high=200)])
        # Same ticker + day, corrected price -> one row, latest wins.
        upsert_prices(db, [_row("AAPL", current=120, low=100, high=200)])
        positions = read_positions(db)
        assert len(positions) == 1
        assert positions[0]["current"] == 120

    def test_read_positions_sorted_by_range_pct(self, tmp_path: Path):
        db = tmp_path / "test.db"
        ensure_schema(db)
        upsert_prices(db, [
            _row("HIGH", current=190, low=100, high=200),  # 0.9
            _row("LOW", current=110, low=100, high=200),   # 0.1
            _row("MID", current=150, low=100, high=200),   # 0.5
        ])
        positions = read_positions(db)
        assert [p["ticker"] for p in positions] == ["LOW", "MID", "HIGH"]

    def test_read_positions_filters_by_ticker(self, tmp_path: Path):
        db = tmp_path / "test.db"
        ensure_schema(db)
        upsert_prices(db, [
            _row("AAPL", current=150, low=100, high=200),
            _row("MSFT", current=180, low=100, high=200),
        ])
        positions = read_positions(db, tickers=["AAPL"])
        assert [p["ticker"] for p in positions] == ["AAPL"]


class TestRefreshPrices:
    def test_refresh_persists_all_with_fake_fetcher(self, tmp_path: Path):
        db = tmp_path / "test.db"
        ensure_schema(db)

        def fake_fetcher(ticker: str, **_kw) -> PriceRow:
            table = {
                "AAPL": (150, 100, 200),
                "MSFT": (180, 100, 200),
                "NVDA": (120, 100, 200),
            }
            cur, low, high = table[ticker]
            return _row(ticker, current=cur, low=low, high=high)

        result = refresh_prices(db, ["AAPL", "MSFT", "NVDA"], api_key="x", fetcher=fake_fetcher)
        assert result["fetched"] == 3
        assert result["errors"] == []
        assert len(read_positions(db)) == 3

    def test_refresh_records_per_ticker_errors_and_continues(self, tmp_path: Path):
        db = tmp_path / "test.db"
        ensure_schema(db)

        def flaky_fetcher(ticker: str, **_kw) -> PriceRow:
            if ticker == "BAD":
                raise RuntimeError("finnhub said no")
            return _row(ticker, current=150, low=100, high=200)

        result = refresh_prices(db, ["AAPL", "BAD", "MSFT"], api_key="x", fetcher=flaky_fetcher)
        assert result["fetched"] == 2
        assert [e["ticker"] for e in result["errors"]] == ["BAD"]
        # The two good tickers still landed.
        assert {p["ticker"] for p in read_positions(db)} == {"AAPL", "MSFT"}


class TestTrackedTickers:
    def _seed_companies(self, db: Path) -> None:
        with sqlite3.connect(db) as conn:
            conn.execute(
                "CREATE TABLE companies (id INTEGER PRIMARY KEY, ticker TEXT, name TEXT, status TEXT)"
            )
            conn.executemany(
                "INSERT INTO companies (ticker, name, status) VALUES (?, ?, ?)",
                [
                    ("AAPL", "Apple", "owned"),
                    ("MSFT", "Microsoft", "tracking"),
                    ("OLD", "Exited Co", "exited"),
                    ("NO", "Passed Co", "passed"),
                    (None, "Private Co", "tracking"),  # null ticker excluded
                ],
            )
            conn.commit()

    def test_defaults_to_tracking_and_owned(self, tmp_path: Path):
        db = tmp_path / "test.db"
        self._seed_companies(db)
        assert tracked_tickers(db) == ["AAPL", "MSFT"]

    def test_status_override(self, tmp_path: Path):
        db = tmp_path / "test.db"
        self._seed_companies(db)
        assert tracked_tickers(db, statuses=("exited",)) == ["OLD"]


class TestRateLimiter:
    def test_spacing_enforced(self):
        limiter = RateLimiter(min_interval=0.05)
        start = time.monotonic()
        limiter.acquire()  # first is immediate
        limiter.acquire()  # second waits >= min_interval
        elapsed = time.monotonic() - start
        assert elapsed >= 0.05
