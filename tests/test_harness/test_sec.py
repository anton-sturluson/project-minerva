"""Tests for SEC command wrappers."""

from pathlib import Path

import pandas as pd

from harness.cli import dispatch_command
from harness.commands import sec
from harness.config import HarnessSettings


def test_sec_dispatch_requires_subcommand(tmp_path: Path) -> None:
    settings = HarnessSettings(workspace_root=tmp_path)
    result = dispatch_command(["sec"], settings=settings)
    assert result.exit_code == 1
    assert "Usage: sec <10k|13f|financials>" in result.stderr.decode("utf-8")


def test_sec_subcommands_validate_missing_args(tmp_path: Path) -> None:
    settings = HarnessSettings(workspace_root=tmp_path)
    ten_k = sec.dispatch(["10k"], settings)
    thirteen_f = sec.dispatch(["13f"], settings)
    financials = sec.dispatch(["financials"], settings)

    assert ten_k.exit_code == 1
    assert "Usage: sec 10k <ticker>" in ten_k.stderr.decode("utf-8")
    assert thirteen_f.exit_code == 1
    assert "Usage: sec 13f <cik>" in thirteen_f.stderr.decode("utf-8")
    assert financials.exit_code == 1
    assert "Usage: sec financials <ticker>" in financials.stderr.decode("utf-8")


def test_get_10k_command_formats_requested_items(tmp_path: Path, monkeypatch) -> None:
    settings = HarnessSettings(workspace_root=tmp_path)
    monkeypatch.setattr(
        "harness.commands.sec.get_10k_items",
        lambda ticker, items: {
            "1": "Business overview",
            "1A": "Risk factors overview",
        },
    )

    result = sec.get_10k_command("MSFT", items=["1", "1A"], settings=settings)
    output: str = result.stdout.decode("utf-8")

    assert result.exit_code == 0
    assert "## Item 1" in output
    assert "Business overview" in output
    assert "## Item 1A" in output
    assert "Risk factors overview" in output


def test_get_13f_command_formats_comparison_sections(tmp_path: Path, monkeypatch) -> None:
    settings = HarnessSettings(workspace_root=tmp_path)
    comparison = {
        "current": pd.DataFrame([{"issuer": "AAA"}, {"issuer": "BBB"}]),
        "previous": pd.DataFrame([{"issuer": "AAA"}]),
        "new": pd.DataFrame([{"issuer": "BBB", "value": 20}]),
        "exited": pd.DataFrame([{"issuer": "CCC", "value": 10}]),
        "increased": pd.DataFrame([{"issuer": "AAA", "value": 30}]),
        "decreased": pd.DataFrame([{"issuer": "DDD", "value": 5}]),
    }
    monkeypatch.setattr("harness.commands.sec.get_13f_comparison", lambda cik: comparison)

    result = sec.get_13f_command("1067983", settings=settings)
    output: str = result.stdout.decode("utf-8")

    assert result.exit_code == 0
    assert "current positions: 2" in output
    assert "previous positions: 1" in output
    assert "new positions: 1" in output
    assert "## New" in output
    assert "| issuer | value |" in output
    assert "| BBB | 20 |" in output
    assert "## Decreased" in output


def test_get_financials_command_formats_statement_output(tmp_path: Path, monkeypatch) -> None:
    settings = HarnessSettings(workspace_root=tmp_path)

    class _FakeCompany:
        def __init__(self, ticker: str) -> None:
            self.ticker = ticker

        def get_filings(self, form: str):
            assert form == "10-K"
            return self

        def latest(self, periods: int):
            assert periods == 3
            return self

        def income_statement(self, *, periods: int, period: str, as_dataframe: bool):
            assert periods == 3
            assert period == "annual"
            assert as_dataframe is True
            return pd.DataFrame({"2024": [100.0], "2023": [90.0]}, index=["Revenue"])

    monkeypatch.setattr("harness.commands.sec.Company", _FakeCompany)

    result = sec.get_financials_command("MSFT", periods=3, statement_type="income", settings=settings)
    output: str = result.stdout.decode("utf-8")

    assert result.exit_code == 0
    assert "# MSFT Income Financials" in output
    assert "| index | 2024 | 2023 |" in output
    assert "| Revenue | 100 | 90 |" in output
