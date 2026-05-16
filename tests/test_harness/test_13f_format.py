"""Integration tests for clean 13F comparison formatting."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from harness.commands import sec as sec_commands
from harness.config import HarnessSettings
from minerva.sec import format_13f_report

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "13f"


def _fixture_comparison(prefix: str) -> dict[str, pd.DataFrame]:
    """Build the same comparison shape as get_13f_comparison from CSV fixtures."""
    current = pd.read_csv(FIXTURE_DIR / f"{prefix}-current.csv")
    previous = pd.read_csv(FIXTURE_DIR / f"{prefix}-previous.csv")

    merged = current.merge(
        previous,
        on=["Cusip"],
        how="outer",
        suffixes=("_current", "_previous"),
        indicator=True,
    )

    new_positions = merged[merged["_merge"] == "left_only"].copy()
    exited_positions = merged[merged["_merge"] == "right_only"].copy()
    both = merged[merged["_merge"] == "both"].copy()

    increased = both[both["SharesPrnAmount_current"] > both["SharesPrnAmount_previous"]].copy()
    decreased = both[both["SharesPrnAmount_current"] < both["SharesPrnAmount_previous"]].copy()
    unchanged = both[both["SharesPrnAmount_current"] == both["SharesPrnAmount_previous"]].copy()

    return {
        "manager_name": prefix.replace("-", " ").title(),
        "current_period": "Q1 2026 (2026-03-31)",
        "previous_period": "Q4 2025 (2025-12-31)",
        "current": current,
        "previous": previous,
        "comparison": merged,
        "new": new_positions,
        "exited": exited_positions,
        "increased": increased,
        "decreased": decreased,
        "unchanged": unchanged,
    }


def _section(report: str, heading: str) -> str:
    marker = f"### {heading}"
    assert marker in report
    tail = report.split(marker, 1)[1]
    next_heading = tail.find("\n### ")
    if next_heading == -1:
        return tail
    return tail[:next_heading]


def _table_rows(section: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in section.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if cells and all(set(cell) <= {"-", ":", " "} for cell in cells):
            continue
        rows.append(cells)
    return rows


def _tickers_in_section(report: str, heading: str) -> list[str]:
    rows = _table_rows(_section(report, heading))
    if len(rows) <= 1:
        return []
    header = rows[0]
    ticker_index = header.index("Ticker")
    return [row[ticker_index] for row in rows[1:]]


def test_format_report_summary_stats() -> None:
    comparison = _fixture_comparison("pershing-square")

    report = format_13f_report(comparison)

    assert "## 13F-HR QoQ Comparison: Pershing Square" in report
    assert "Period: Q1 2026 (2026-03-31) vs Q4 2025 (2025-12-31)" in report
    assert "### Summary" in report
    assert "Positions: 11 (prev: 11) | New: 1 | Exited: 1 | Increased: 1 | Decreased: 6 | Unchanged: 3" in report
    assert "Portfolio value: $13,714M (prev: $15,527M, Δ -11.7%)" in report
    assert "Net new capital deployed: $2,093M" in report
    assert "Net capital exited: $870M" in report


def test_format_report_new_positions() -> None:
    report = format_13f_report(_fixture_comparison("pershing-square"))

    new_positions = _section(report, "New Positions")

    assert "MSFT" in new_positions
    assert "MICROSOFT CORP" in new_positions
    assert "$2,093M" in new_positions
    assert "15.3%" in new_positions
    assert "nan" not in new_positions.lower()


def test_format_report_exited_positions() -> None:
    report = format_13f_report(_fixture_comparison("pershing-square"))

    exited_positions = _section(report, "Exited Positions")

    assert "HLT" in exited_positions
    assert "HILTON WORLDWIDE HLDGS INC" in exited_positions
    assert "$870M" in exited_positions
    assert "5.6%" in exited_positions
    assert "nan" not in exited_positions.lower()


def test_format_report_increased_decreased_uses_share_count() -> None:
    report = format_13f_report(_fixture_comparison("pershing-square"))

    increased_tickers = _tickers_in_section(report, "Increased")
    decreased_tickers = _tickers_in_section(report, "Decreased")
    unchanged_tickers = _tickers_in_section(report, "Unchanged")

    assert "AMZN" in increased_tickers
    assert "GOOG" in decreased_tickers
    assert "HTZ" in unchanged_tickers
    assert "HHH" in unchanged_tickers
    assert "HTZ" not in increased_tickers + decreased_tickers
    assert "HHH" not in increased_tickers + decreased_tickers


def test_format_report_sorting() -> None:
    report = format_13f_report(_fixture_comparison("pershing-square"))

    decreased_tickers = _tickers_in_section(report, "Decreased")

    assert decreased_tickers[:2] == ["GOOGL", "GOOG"]
    decreased_section = _section(report, "Decreased")
    assert "-95.2%" in decreased_section
    assert "-94.9%" in decreased_section


def test_format_report_weight_calculation() -> None:
    report = format_13f_report(_fixture_comparison("pershing-square"))

    new_positions = _section(report, "New Positions")
    increased = _section(report, "Increased")
    decreased = _section(report, "Decreased")
    unchanged = _section(report, "Unchanged")

    # MSFT current weight: 2,092,970,053 / 13,714,299,861 = 15.3%.
    assert "15.3%" in new_positions
    # AMZN current weight rose from 14.3% to 17.4%, a +3.1pp shift.
    assert "+3.1pp" in increased
    # GOOG current weight fell from 12.5% to 0.7%, an -11.8pp shift.
    assert "-11.8pp" in decreased
    # HHH shares were unchanged but its portfolio weight shifted with price/portfolio moves.
    assert "HHH" in unchanged
    assert "-1.0pp" in unchanged

    current = _fixture_comparison("pershing-square")["current"]
    weights = current["Value"] / current["Value"].sum()
    assert round(weights.sum() * 100, 1) == 100.0


def test_format_report_no_nans() -> None:
    report = format_13f_report(_fixture_comparison("pershing-square"))

    assert "nan" not in report.lower()


def test_format_report_putcall_column_hidden_when_empty() -> None:
    report = format_13f_report(_fixture_comparison("pershing-square"))

    assert "Put/Call" not in report


def test_format_report_high_turnover() -> None:
    report = format_13f_report(_fixture_comparison("duquesne"))

    assert "New: 30 | Exited: 22" in report
    assert "### New Positions" in report
    assert "### Exited Positions" in report
    assert len(_tickers_in_section(report, "New Positions")) == 30
    assert len(_tickers_in_section(report, "Exited Positions")) == 22
    assert "nan" not in report.lower()


def test_cli_13f_output_flag(tmp_path: Path, monkeypatch) -> None:
    settings = HarnessSettings(workspace_root=tmp_path, edgar_identity="Minerva Research minerva@example.com")
    comparison = _fixture_comparison("pershing-square")
    output_path = tmp_path / "pershing-13f.md"

    monkeypatch.setattr("harness.commands.sec.get_13f_comparison", lambda cik: comparison)
    monkeypatch.setattr("harness.commands.sec._configure_edgar", lambda settings: None)

    result = sec_commands.get_13f_command("1067983", output_path=str(output_path), settings=settings)

    assert result.exit_code == 0
    written = output_path.read_text(encoding="utf-8")
    assert written.startswith("## 13F-HR QoQ Comparison: Pershing Square")
    assert "MSFT" in written
    assert "saved_to: " in result.stdout.decode("utf-8")


def test_normalize_value_units_thousands() -> None:
    """Values reported in thousands (sum < $100M) should be multiplied by 1,000."""
    from minerva.sec import _normalize_value_units

    # Simulate a filer reporting in thousands (like Baupost/Duquesne)
    df = pd.DataFrame({
        "Issuer": ["AMAZON COM INC", "ALPHABET INC", "META PLATFORMS"],
        "Value": [649_543, 350_000, 200_000],  # thousands: $650M, $350M, $200M
        "SharesPrnAmount": [3_000_000, 1_000_000, 500_000],
    })
    result = _normalize_value_units(df)
    assert result["Value"].sum() == (649_543 + 350_000 + 200_000) * 1_000
    assert result["Value"].iloc[0] == 649_543_000
    # Shares should be untouched
    assert result["SharesPrnAmount"].iloc[0] == 3_000_000


def test_normalize_value_units_dollars_unchanged() -> None:
    """Values already in dollars (sum >= $100M) should be left as-is."""
    from minerva.sec import _normalize_value_units

    df = pd.DataFrame({
        "Issuer": ["AMAZON COM INC", "ALPHABET INC"],
        "Value": [2_385_104_083, 1_934_222_720],  # actual dollars
        "SharesPrnAmount": [11_000_000, 6_000_000],
    })
    result = _normalize_value_units(df)
    assert result["Value"].iloc[0] == 2_385_104_083
    assert result["Value"].sum() == 2_385_104_083 + 1_934_222_720
