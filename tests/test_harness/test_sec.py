"""Tests for SEC command wrappers."""

from pathlib import Path

import pandas as pd

from harness.commands import sec
from harness.config import HarnessSettings
from minerva import sec as minerva_sec


def test_sec_dispatch_requires_subcommand(tmp_path: Path) -> None:
    settings = HarnessSettings(workspace_root=tmp_path)
    result = sec.dispatch([], settings=settings)
    assert result.exit_code == 1
    assert "What went wrong:" in result.stderr.decode("utf-8")
    assert "SEC EDGAR filing tools." in result.stderr.decode("utf-8")


def test_get_10k_command_formats_requested_items(tmp_path: Path, monkeypatch) -> None:
    settings = HarnessSettings(workspace_root=tmp_path, edgar_identity="Minerva Research minerva@example.com")
    monkeypatch.setattr(
        "harness.commands.sec.get_10k_items",
        lambda ticker, items: {"1": "Business overview", "1A": "Risk factors overview"},
    )
    monkeypatch.setattr("harness.commands.sec._configure_edgar", lambda settings: None)

    result = sec.get_10k_command("MSFT", items=["1", "1A"], settings=settings)
    output = result.stdout.decode("utf-8")

    assert result.exit_code == 0
    assert "## Item 1" in output
    assert "Business overview" in output
    assert "## Item 1A" in output


def test_get_13f_command_formats_comparison_sections(tmp_path: Path, monkeypatch) -> None:
    settings = HarnessSettings(workspace_root=tmp_path, edgar_identity="Minerva Research minerva@example.com")
    comparison = {
        "current": pd.DataFrame([{"issuer": "AAA"}, {"issuer": "BBB"}]),
        "previous": pd.DataFrame([{"issuer": "AAA"}]),
        "new": pd.DataFrame([{"issuer": "BBB", "value": 20}]),
        "exited": pd.DataFrame([{"issuer": "CCC", "value": 10}]),
        "increased": pd.DataFrame([{"issuer": "AAA", "value": 30}]),
        "decreased": pd.DataFrame([{"issuer": "DDD", "value": 5}]),
    }
    monkeypatch.setattr("harness.commands.sec.get_13f_comparison", lambda cik: comparison)
    monkeypatch.setattr("harness.commands.sec._configure_edgar", lambda settings: None)

    result = sec.get_13f_command("1067983", settings=settings)
    output = result.stdout.decode("utf-8")

    assert result.exit_code == 0
    assert "current positions: 2" in output
    assert "## New" in output
    assert "| BBB | 20 |" in output


def test_get_financials_command_formats_statement_output(tmp_path: Path, monkeypatch) -> None:
    settings = HarnessSettings(workspace_root=tmp_path, edgar_identity="Minerva Research minerva@example.com")

    class _FakeCompany:
        def __init__(self, ticker: str) -> None:
            self.ticker = ticker

        def income_statement(self, *, periods: int, period: str, as_dataframe: bool):
            assert periods == 3
            assert period == "annual"
            assert as_dataframe is True
            return pd.DataFrame({"2024": [100.0], "2023": [90.0]}, index=["Revenue"])

    monkeypatch.setattr("harness.commands.sec.Company", _FakeCompany)
    monkeypatch.setattr("harness.commands.sec._configure_edgar", lambda settings: None)

    result = sec.get_financials_command("MSFT", periods=3, statement_type="income", settings=settings)
    output = result.stdout.decode("utf-8")

    assert result.exit_code == 0
    assert "# MSFT Income Financials" in output
    assert "| Revenue | 100 | 90 |" in output


def test_download_filing_command_saves_markdown(tmp_path: Path, monkeypatch) -> None:
    settings = HarnessSettings(workspace_root=tmp_path, edgar_identity="Minerva Research minerva@example.com")

    class _FakeFiling:
        filing_date = "2025-11-01"
        accession_number = "000000"

        def markdown(self) -> str:
            return "# Filing"

    class _FakeFilings:
        def latest(self, count: int):
            return _FakeFiling()

    class _FakeCompany:
        def __init__(self, ticker: str) -> None:
            self.ticker = ticker

        def get_filings(self, *, form: str):
            assert form == "10-K"
            return _FakeFilings()

    monkeypatch.setattr("harness.commands.sec.Company", _FakeCompany)
    monkeypatch.setattr("harness.commands.sec._configure_edgar", lambda settings: None)

    result = sec.download_filing_command("AAPL", form="10-K", file_format="markdown", output_path=str(tmp_path / "aapl.md"), settings=settings)
    assert result.exit_code == 0
    assert (tmp_path / "aapl.md").read_text(encoding="utf-8") == "# Filing"


def test_minerva_sec_helper_uses_correct_13f_form_code(monkeypatch) -> None:
    observed: dict[str, str] = {}

    class _FakeCompany:
        def __init__(self, cik: str) -> None:
            self.cik = cik

        def get_filings(self, *, form: str):
            observed["form"] = form

            class _FakeFilings:
                def latest(self, count: int):
                    return []

            return _FakeFilings()

    monkeypatch.setattr("minerva.sec.Company", _FakeCompany)
    try:
        minerva_sec.get_13f_comparison("1067983")
    except ValueError:
        pass

    assert observed["form"] == "13F-HR"
