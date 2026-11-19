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
    current = pd.DataFrame(
        [
            {
                "Issuer": "AAA CORP",
                "Class": "COM",
                "Cusip": "000000001",
                "Ticker": "AAA",
                "SharesPrnAmount": 110,
                "Value": 30_000_000,
                "PutCall": "",
            },
            {
                "Issuer": "BBB CORP",
                "Class": "COM",
                "Cusip": "000000002",
                "Ticker": "BBB",
                "SharesPrnAmount": 200,
                "Value": 20_000_000,
                "PutCall": "",
            },
        ]
    )
    previous = pd.DataFrame(
        [
            {
                "Issuer": "AAA CORP",
                "Class": "COM",
                "Cusip": "000000001",
                "Ticker": "AAA",
                "SharesPrnAmount": 100,
                "Value": 25_000_000,
                "PutCall": "",
            },
            {
                "Issuer": "CCC CORP",
                "Class": "COM",
                "Cusip": "000000003",
                "Ticker": "CCC",
                "SharesPrnAmount": 300,
                "Value": 10_000_000,
                "PutCall": "",
            },
        ]
    )
    merged = current.merge(previous, on=["Cusip"], how="outer", suffixes=("_current", "_previous"), indicator=True)
    both = merged[merged["_merge"] == "both"].copy()
    comparison = {
        "manager_name": "Example Manager",
        "current_period": "Q1 2026 (2026-03-31)",
        "previous_period": "Q4 2025 (2025-12-31)",
        "current": current,
        "previous": previous,
        "comparison": merged,
        "new": merged[merged["_merge"] == "left_only"].copy(),
        "exited": merged[merged["_merge"] == "right_only"].copy(),
        "increased": both[both["SharesPrnAmount_current"] > both["SharesPrnAmount_previous"]].copy(),
        "decreased": both[both["SharesPrnAmount_current"] < both["SharesPrnAmount_previous"]].copy(),
        "unchanged": both[both["SharesPrnAmount_current"] == both["SharesPrnAmount_previous"]].copy(),
    }
    monkeypatch.setattr("harness.commands.sec.get_13f_comparison", lambda cik: comparison)
    monkeypatch.setattr("harness.commands.sec._configure_edgar", lambda settings: None)

    result = sec.get_13f_command("1067983", settings=settings)
    output = result.stdout.decode("utf-8")

    assert result.exit_code == 0
    assert "## 13F-HR QoQ Comparison: Example Manager" in output
    assert "Positions: 2 (prev: 2) | New: 1 | Exited: 1 | Increased: 1" in output
    assert "### New Positions" in output
    assert "| BBB | BBB CORP | COM | 200 | $20M | 40.0% |" in output
    assert "### Increased" in output
    assert "| AAA | AAA CORP | COM | 110 | +10 | +10.0% | $30M | +$5M | 60.0% |" in output


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
        form = "10-K"
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

        def get_filings(self, *, form: str, amendments: bool):
            assert form == "10-K"
            assert amendments is False
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


def test_minerva_sec_helper_uses_holdings_dataframe_directly(monkeypatch) -> None:
    expected_current = pd.DataFrame([{"cusip": "123", "value": 200_000_000}])
    expected_previous = pd.DataFrame([{"cusip": "123", "value": 100_000_000}])

    class _FakeThirteenF:
        def __init__(self, holdings: pd.DataFrame) -> None:
            self.holdings = holdings

    class _FakeFilingWrapper:
        def __init__(self, holdings: pd.DataFrame) -> None:
            self._holdings = holdings

        def obj(self) -> _FakeThirteenF:
            return _FakeThirteenF(self._holdings)

    class _FakeFilings:
        def latest(self, count: int):
            assert count == 2
            return [
                _FakeFilingWrapper(expected_current),
                _FakeFilingWrapper(expected_previous),
            ]

    class _FakeCompany:
        def __init__(self, cik: str) -> None:
            self.cik = cik

        def get_filings(self, *, form: str):
            assert form == "13F-HR"
            return _FakeFilings()

    monkeypatch.setattr("minerva.sec.Company", _FakeCompany)

    comparison = minerva_sec.get_13f_comparison("1067983")

    assert comparison["current"].equals(expected_current)
    assert comparison["previous"].equals(expected_previous)


def test_bulk_download_uses_complete_pairs_not_selected_items(tmp_path: Path, monkeypatch) -> None:
    from types import SimpleNamespace
    settings = HarnessSettings(workspace_root=tmp_path)
    filing = SimpleNamespace(form="10-K", accession_no="0000001", filing_date="2026-11-01")
    monkeypatch.setattr(sec, "Company", lambda ticker: object())
    monkeypatch.setattr(sec, "_configure_edgar", lambda settings: None)
    monkeypatch.setattr(sec, "_list_filings", lambda company, form, limit: [filing] if form == "10-K" else [])
    seen = []
    def collect(source, stem):
        seen.append((source, stem))
        assert source is filing
        assert stem.name == "filing"
    monkeypatch.setattr(sec, "collect_filing", collect)
    result = sec.bulk_download_command(ticker="EXAMPLE", output_dir=str(tmp_path), annual=1, quarters=0, earnings=0, include_financials=False, settings=settings)
    assert result.exit_code == 0
    assert len(seen) == 1
    assert "2026-11-01-0000001" in str(seen[0][1])
