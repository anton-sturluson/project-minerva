"""Focused tests for ``news download-market-data``."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from typer.testing import CliRunner

from harness.cli import app
from harness.commands import news as news_commands
from harness.config import HarnessSettings
from harness.portfolio_state import portfolio_paths, write_json

runner = CliRunner()


def _workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    paths = portfolio_paths(workspace)
    paths.current.mkdir(parents=True)
    write_json(
        paths.universe,
        [
            {"ticker": "AAPL", "exchange": "NASDAQ"},
            {"ticker": "TOI", "exchange": "TSXV"},
        ],
    )
    return workspace


def test_market_instruments_use_default_or_explicit_indexes_and_symbols(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    defaults = news_commands.market_instruments(
        workspace, indexes=None, symbols=["nvda", "^gspc"]
    )
    custom = news_commands.market_instruments(
        workspace, indexes=["^STOXX50E"], symbols=["BTC-USD"]
    )

    assert [item[0] for item in defaults] == [
        "AAPL",
        "TOI",
        "^GSPC",
        "^IXIC",
        "^DJI",
        "^RUT",
        "^VIX",
        "NVDA",
    ]
    assert [item[0] for item in custom] == ["AAPL", "TOI", "^STOXX50E", "BTC-USD"]
    assert {symbol: kind for symbol, _, kind in custom} == {
        "AAPL": "security",
        "TOI": "security",
        "^STOXX50E": "index",
        "BTC-USD": "security",
    }


def test_download_market_data_cli_emits_compact_accounting(
    tmp_path: Path, monkeypatch
) -> None:
    workspace = _workspace(tmp_path)
    db_path = tmp_path / "invest.db"

    def fake_download(db, instruments, target_date):
        assert (db, target_date) == (db_path, date(2026, 7, 5))
        assert [item[0] for item in instruments] == ["AAPL", "TOI", "^GSPC", "BAD"]
        return {
            "requested": 4,
            "written": 3,
            "trading_dates": ["2026-07-02"],
            "errors": [{"symbol": "BAD", "error": "no chart data"}],
        }

    monkeypatch.setattr(
        news_commands,
        "get_settings",
        lambda: HarnessSettings(workspace_root=workspace),
    )
    monkeypatch.setattr(news_commands.prices_mod, "download_market_data", fake_download)
    result = runner.invoke(
        app,
        [
            "news",
            "download-market-data",
            "--date",
            "2026-07-05",
            "--db",
            str(db_path),
            "--index",
            "^GSPC",
            "--symbol",
            "BAD",
        ],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {
        "errors": [{"error": "no chart data", "symbol": "BAD"}],
        "requested": 4,
        "trading_dates": ["2026-07-02"],
        "written": 3,
    }
