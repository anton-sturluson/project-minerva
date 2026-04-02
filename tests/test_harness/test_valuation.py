"""Tests for valuation commands."""

from pathlib import Path

from harness.commands.valuation import run_dcf_command
from harness.config import HarnessSettings


def test_dcf_command_returns_expected_price_per_share(tmp_path: Path) -> None:
    settings = HarnessSettings(workspace_root=tmp_path)
    result = run_dcf_command(
        revenue=100.0,
        fcf=20.0,
        growth_rates_csv="0.1,0.1",
        margins_csv="0.2,0.2",
        wacc=0.1,
        terminal_growth=0.03,
        shares=10.0,
        net_cash=0.0,
        years=2,
        settings=settings,
    )
    output: str = result.stdout.decode("utf-8")
    assert result.exit_code == 0
    assert "price_per_share: $33.43" in output
    assert "| 1 | $110.00 | 10.0% | $22.00 | 20.0% | 0.909 | $20.00 |" in output
