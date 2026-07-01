"""Command-level tests for `portfolio prices` — read path and no-key guard.

The live-fetch path is covered by minerva.prices unit tests (injectable fetcher);
here we only exercise the harness wiring around it, with no network.
"""

from __future__ import annotations

from pathlib import Path

from harness.commands import portfolio
from harness.config import HarnessSettings
from minerva.prices import PriceRow, default_db_path, ensure_schema, upsert_prices


def _settings(tmp_path: Path, *, key: str | None = None) -> HarnessSettings:
    ws = tmp_path / "hard-disk"
    (ws / "data" / "04-database").mkdir(parents=True)
    return HarnessSettings(workspace_root=ws, finnhub_api_key=key)


def test_read_only_renders_stored_table(tmp_path: Path):
    settings = _settings(tmp_path)
    db = default_db_path(settings.ensure_workspace_root())
    ensure_schema(db)
    upsert_prices(db, [PriceRow("AAPL", "2026-07-01", current=150, wk52_low=100, wk52_high=200)])

    result = portfolio.prices_command(tickers=[], refresh=False, all_status=False, settings=settings)
    out = result.stdout.decode()
    assert result.exit_code == 0
    assert "AAPL" in out
    assert "0.5000" in out


def test_empty_table_message(tmp_path: Path):
    settings = _settings(tmp_path)
    result = portfolio.prices_command(tickers=[], refresh=False, all_status=False, settings=settings)
    assert result.exit_code == 0
    assert "no price data" in result.stdout.decode()


def test_fetch_without_api_key_errors(tmp_path: Path):
    settings = _settings(tmp_path, key=None)
    result = portfolio.prices_command(tickers=["AAPL"], refresh=False, all_status=False, settings=settings)
    assert result.exit_code != 0
    assert "FINNHUB_API_KEY" in result.stderr.decode()
