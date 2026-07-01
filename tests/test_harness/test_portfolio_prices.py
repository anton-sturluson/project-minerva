"""Command-level tests for `portfolio prices` — read path only, no network.

The live-fetch path is covered by minerva.prices unit tests (injectable fetcher);
here we only exercise the harness read/render wiring.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from harness.commands import portfolio
from harness.config import HarnessSettings
from minerva.prices import PriceRow, default_db_path, ensure_schema, upsert_prices


def _settings(tmp_path: Path) -> HarnessSettings:
    ws = tmp_path / "hard-disk"
    (ws / "data" / "04-database").mkdir(parents=True)
    return HarnessSettings(workspace_root=ws)


def _seed_companies(db: Path, rows: list[tuple[str, str | None]]) -> None:
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS companies (id INTEGER PRIMARY KEY, ticker TEXT, exchange TEXT)")
        conn.executemany("INSERT INTO companies (ticker, exchange) VALUES (?, ?)", rows)
        conn.commit()


def test_read_only_renders_stored_table(tmp_path: Path):
    settings = _settings(tmp_path)
    db = default_db_path(settings.ensure_workspace_root())
    ensure_schema(db)
    _seed_companies(db, [("AAPL", None), ("TOI", "TSXV")])
    upsert_prices(db, [
        PriceRow("AAPL", "2026-07-01", current=150, wk52_low=100, wk52_high=200, currency="USD"),
        PriceRow("TOI", "2026-07-01", current=90, wk52_low=80, wk52_high=200, currency="CAD"),
    ])

    result = portfolio.prices_command(tickers=[], refresh=False, settings=settings)
    out = result.stdout.decode()
    assert result.exit_code == 0
    assert "AAPL" in out
    assert "0.5000" in out
    assert "USD" in out
    # US names show US; foreign names show their exchange code.
    assert "US" in out
    assert "TSXV" in out


def test_empty_table_message(tmp_path: Path):
    settings = _settings(tmp_path)
    result = portfolio.prices_command(tickers=[], refresh=False, settings=settings)
    assert result.exit_code == 0
    assert "no price data" in result.stdout.decode()



