"""Tests for valuation commands."""

import json
from pathlib import Path

from harness.commands.valuation import (
    run_comps_command,
    run_dcf_command,
    run_report_command,
    run_reverse_dcf_command,
    run_sotp_command,
)
from harness.config import HarnessSettings


def test_dcf_command_defaults_fcf_to_revenue_times_first_margin_and_exports(tmp_path: Path) -> None:
    settings = HarnessSettings(workspace_root=tmp_path)
    export_path = tmp_path / "dcf.md"
    result = run_dcf_command(
        revenue=100.0,
        fcf=None,
        growth_rates_csv="0.1,0.1",
        margins_csv="0.2,0.2",
        wacc=0.1,
        terminal_growth=0.03,
        shares=10.0,
        net_cash=0.0,
        years=2,
        export_path=str(export_path),
        settings=settings,
    )
    output = result.stdout.decode("utf-8")
    assert result.exit_code == 0
    assert "base_fcf: $20.00" in output
    assert "price_per_share: $33.43" in output
    assert export_path.exists()


def test_comps_command_returns_expected_table(tmp_path: Path) -> None:
    settings = HarnessSettings(workspace_root=tmp_path)
    result = run_comps_command(
        ntm_revenue=200.0,
        ntm_ebitda=40.0,
        ntm_fcf=30.0,
        shares=20.0,
        net_cash=50.0,
        ev_rev=6.0,
        ev_ebitda=18.0,
        p_fcf=25.0,
        settings=settings,
    )
    output = result.stdout.decode("utf-8")
    assert result.exit_code == 0
    assert "| EV/Revenue | $1.20K | $1.25K | $62.50 |" in output
    assert "| P/FCF | N/A | $750.00 | $37.50 |" in output


def test_reverse_dcf_command_returns_expected_summary(tmp_path: Path) -> None:
    settings = HarnessSettings(workspace_root=tmp_path)
    result = run_reverse_dcf_command(
        price=25.0,
        shares=20.0,
        net_cash=50.0,
        base_revenue=200.0,
        margins_csv="0.15,0.18,0.2,0.22,0.25",
        wacc=0.1,
        terminal_growth=0.03,
        years=5,
        settings=settings,
    )
    output = result.stdout.decode("utf-8")
    assert result.exit_code == 0
    assert "current_price: $25.00" in output
    assert "implied_revenue_growth: 35.0%" in output


def test_sotp_command_returns_expected_summary_and_table(tmp_path: Path) -> None:
    settings = HarnessSettings(workspace_root=tmp_path)
    segments = json.dumps(
        [
            {"name": "Core", "revenue": 300, "ev_revenue_multiple": 8.0, "notes": "Core SaaS"},
            {"name": "Payments", "revenue": 100, "ev_revenue_multiple": 4.0, "notes": "Lower margin"},
        ]
    )
    result = run_sotp_command(segments_spec=segments, net_cash=100.0, shares=25.0, settings=settings)
    output = result.stdout.decode("utf-8")
    assert result.exit_code == 0
    assert "total_ev: $2.80K" in output
    assert "| Core | $300.00 | 75.0% | 8.0x | $2.40K | Core SaaS |" in output


def test_report_command_writes_markdown_report(tmp_path: Path) -> None:
    settings = HarnessSettings(workspace_root=tmp_path)
    config = {
        "current_price": 25.0,
        "dcf": {
            "revenue": 100.0,
            "growth": "0.1,0.1",
            "margins": "0.2,0.2",
            "wacc": 0.1,
            "terminal_growth": 0.03,
            "shares": 10.0,
            "net_cash": 0.0,
            "years": 2,
        },
        "comps": {
            "ntm_revenue": 120.0,
            "ntm_ebitda": 24.0,
            "ntm_fcf": 18.0,
            "shares": 10.0,
            "net_cash": 0.0,
            "ev_rev": 5.0,
            "ev_ebitda": 15.0,
            "p_fcf": 20.0,
        },
        "reverse_dcf": {
            "price": 25.0,
            "shares": 10.0,
            "net_cash": 0.0,
            "base_revenue": 100.0,
            "margins": "0.2,0.2",
            "wacc": 0.1,
            "terminal_growth": 0.03,
            "years": 2,
        },
        "sotp": {
            "segments": [{"name": "Core", "revenue": 100.0, "revenue_pct": 100.0, "ev_revenue_multiple": 5.0}],
            "net_cash": 0.0,
            "shares": 10.0,
        },
    }
    config_path = tmp_path / "valuation.json"
    output_path = tmp_path / "valuation.md"
    config_path.write_text(json.dumps(config), encoding="utf-8")

    result = run_report_command(ticker="TEST", config_path=str(config_path), output_path=str(output_path), settings=settings)

    assert result.exit_code == 0
    assert output_path.exists()
    assert "# TEST" in output_path.read_text(encoding="utf-8")
