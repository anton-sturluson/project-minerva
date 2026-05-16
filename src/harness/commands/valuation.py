"""Valuation commands."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import typer

from harness.commands.common import (
    abort_with_help,
    elapsed_ms,
    error_result,
    maybe_export_text,
    parse_csv_floats,
    parse_flag_args,
    resolve_path,
)
from harness.config import HarnessSettings, get_settings
from harness.output import CommandResult, OutputEnvelope

VALUATION_HELP = (
    "Financial valuation models.\n\n"
    "Examples:\n"
    "  minerva valuation dcf --revenue 394e9 --growth 0.06,0.05,0.04 --margins 0.28,0.29,0.30 --wacc 0.10 --terminal-growth 0.03 --shares 15.5e9 --net-cash 57e9\n"
    "  minerva valuation comps --ntm-revenue 420e9 --ntm-ebitda 140e9 --ntm-fcf 110e9 --shares 15.5e9 --net-cash 57e9 --ev-rev 8.5 --ev-ebitda 25 --p-fcf 30\n"
    "  minerva valuation report --ticker AAPL --config valuation.json --output valuation.md\n"
)

app = typer.Typer(help=VALUATION_HELP, no_args_is_help=True)
def dispatch(
    args: list[str],
    settings: HarnessSettings,
    stdin: bytes = b"",
) -> CommandResult:
    """Source-of-truth parser for `run` path valuation commands."""
    settings: HarnessSettings = settings
    if not args:
        return CommandResult.from_text(
            "",
            stderr=_usage_error(
                "no `valuation` subcommand was provided",
                "choose one of the supported valuation subcommands",
                ["`valuation dcf --revenue 394e9 ...`", "`valuation comps --ntm-revenue 420e9 ...`"],
                VALUATION_HELP,
            ),
            exit_code=1,
        )

    subcommand: str = args[0]
    try:
        parsed = parse_flag_args(args[1:])
    except ValueError as exc:
        return CommandResult.from_text("", stderr=str(exc), exit_code=1)

    if subcommand == "dcf":
        required = ["revenue", "growth", "margins", "wacc", "terminal-growth", "shares", "net-cash"]
        if missing := [name for name in required if name not in parsed]:
            return _dispatch_help("dcf", missing)
        return run_dcf_command(
            revenue=float(parsed["revenue"]),
            fcf=float(parsed["fcf"]) if "fcf" in parsed else None,
            growth_rates_csv=str(parsed["growth"]),
            margins_csv=str(parsed["margins"]),
            wacc=float(parsed["wacc"]),
            terminal_growth=float(parsed["terminal-growth"]),
            shares=float(parsed["shares"]),
            net_cash=float(parsed["net-cash"]),
            sbc=float(parsed.get("sbc", 0.0)),
            sbc_growth=float(parsed.get("sbc-growth", 0.0)),
            years=int(parsed.get("years", 5)),
            export_path=str(parsed["export"]) if "export" in parsed else None,
            settings=settings,
        )
    if subcommand == "comps":
        required = ["ntm-revenue", "ntm-ebitda", "ntm-fcf", "shares", "net-cash", "ev-rev", "ev-ebitda", "p-fcf"]
        if missing := [name for name in required if name not in parsed]:
            return _dispatch_help("comps", missing)
        return run_comps_command(
            ntm_revenue=float(parsed["ntm-revenue"]),
            ntm_ebitda=float(parsed["ntm-ebitda"]),
            ntm_fcf=float(parsed["ntm-fcf"]),
            shares=float(parsed["shares"]),
            net_cash=float(parsed["net-cash"]),
            ev_rev=float(parsed["ev-rev"]),
            ev_ebitda=float(parsed["ev-ebitda"]),
            p_fcf=float(parsed["p-fcf"]),
            export_path=str(parsed["export"]) if "export" in parsed else None,
            settings=settings,
        )
    if subcommand == "reverse-dcf":
        required = ["price", "shares", "net-cash", "base-revenue", "margins", "wacc", "terminal-growth"]
        if missing := [name for name in required if name not in parsed]:
            return _dispatch_help("reverse-dcf", missing)
        return run_reverse_dcf_command(
            price=float(parsed["price"]),
            shares=float(parsed["shares"]),
            net_cash=float(parsed["net-cash"]),
            base_revenue=float(parsed["base-revenue"]),
            margins_csv=str(parsed["margins"]),
            wacc=float(parsed["wacc"]),
            terminal_growth=float(parsed["terminal-growth"]),
            years=int(parsed.get("years", 5)),
            export_path=str(parsed["export"]) if "export" in parsed else None,
            settings=settings,
        )
    if subcommand == "sotp":
        required = ["segments", "net-cash", "shares"]
        if missing := [name for name in required if name not in parsed]:
            return _dispatch_help("sotp", missing)
        return run_sotp_command(
            segments_spec=str(parsed["segments"]),
            net_cash=float(parsed["net-cash"]),
            shares=float(parsed["shares"]),
            export_path=str(parsed["export"]) if "export" in parsed else None,
            settings=settings,
        )
    if subcommand == "report":
        required = ["ticker", "config", "output"]
        if missing := [name for name in required if name not in parsed]:
            return _dispatch_help("report", missing)
        return run_report_command(
            ticker=str(parsed["ticker"]),
            config_path=str(parsed["config"]),
            output_path=str(parsed["output"]),
            settings=settings,
        )

    return CommandResult.from_text(
        "",
        stderr=_usage_error(
            f"unknown `valuation` subcommand `{subcommand}`",
            "choose one of the supported valuation subcommands",
            ["`valuation dcf --revenue 394e9 ...`", "`valuation report --ticker AAPL --config valuation.json --output valuation.md`"],
            VALUATION_HELP,
        ),
        exit_code=1,
    )
def run_dcf_command(
    *,
    revenue: float,
    fcf: float | None,
    growth_rates_csv: str,
    margins_csv: str,
    wacc: float,
    terminal_growth: float,
    shares: float,
    net_cash: float,
    sbc: float = 0.0,
    sbc_growth: float = 0.0,
    years: int = 5,
    export_path: str | None = None,
    settings: HarnessSettings,
) -> CommandResult:
    start: float = time.perf_counter()
    try:
        from minerva.formatting import build_markdown_table, format_pct, format_usd
        from minerva.valuation import DCFAssumptions, run_dcf

        growth_rates = parse_csv_floats(growth_rates_csv)
        margins = parse_csv_floats(margins_csv)
        base_fcf: float = fcf if fcf is not None else revenue * margins[0]
        assumptions = DCFAssumptions(
            base_revenue=revenue,
            base_fcf=base_fcf,
            revenue_growth_rates=growth_rates,
            fcf_margins=margins,
            wacc=wacc,
            terminal_growth_rate=terminal_growth,
            shares_outstanding=shares,
            net_cash=net_cash,
            sbc_annual=sbc,
            sbc_growth_rate=sbc_growth,
            projection_years=years,
        )
        result = run_dcf(assumptions)
    except Exception as exc:
        return error_result(
            f"failed to run DCF: {exc}",
            "provide numeric inputs and a valid growth/margin trajectory",
            ["`valuation comps --ntm-revenue ...`", "`valuation reverse-dcf --price ...`"],
            start,
        )

    rows: list[list[str]] = []
    for projection in result.projections:
        rows.append(
            [
                str(projection.year),
                format_usd(projection.revenue),
                format_pct(projection.revenue_growth * 100),
                format_usd(projection.fcf),
                format_pct(projection.fcf_margin * 100),
                f"{projection.discount_factor:.3f}",
                format_usd(projection.pv_fcf),
            ]
        )
    assumptions_block = "\n".join(
        [
            "## Assumptions",
            "",
            f"base_revenue: {format_usd(revenue)}",
            f"base_fcf: {format_usd(assumptions.base_fcf)}",
            f"wacc: {format_pct(wacc * 100)}",
            f"terminal_growth: {format_pct(terminal_growth * 100)}",
            f"shares: {shares:,.0f}",
            f"net_cash: {format_usd(net_cash)}",
        ]
    )
    projection_table: str = build_markdown_table(
        ["year", "revenue", "growth", "fcf", "fcf_margin", "discount_factor", "pv_fcf"],
        rows,
        alignment=["r"] * 7,
    )
    summary = "\n".join(
        [
            "## Valuation Bridge",
            "",
            f"enterprise_value: {format_usd(result.enterprise_value)}",
            f"equity_value: {format_usd(result.equity_value)}",
            f"equity_value_ex_sbc: {format_usd(result.equity_value_ex_sbc)}",
            f"price_per_share: {format_usd(result.price_per_share, auto_scale=False)}",
            f"price_per_share_ex_sbc: {format_usd(result.price_per_share_ex_sbc, auto_scale=False)}",
        ]
    )
    output = f"{assumptions_block}\n\n## Projections\n\n{projection_table}\n\n{summary}"
    output += maybe_export_text(output, export_path)
    return CommandResult.from_text(output, duration_ms=elapsed_ms(start))
def run_comps_command(
    *,
    ntm_revenue: float,
    ntm_ebitda: float,
    ntm_fcf: float,
    shares: float,
    net_cash: float,
    ev_rev: float,
    ev_ebitda: float,
    p_fcf: float,
    export_path: str | None = None,
    settings: HarnessSettings,
) -> CommandResult:
    start: float = time.perf_counter()
    try:
        from minerva.formatting import build_markdown_table, format_usd
        from minerva.valuation import CompsAssumptions, run_comps

        assumptions = CompsAssumptions(
            ntm_revenue=ntm_revenue,
            ntm_ebitda=ntm_ebitda,
            ntm_fcf=ntm_fcf,
            shares_outstanding=shares,
            net_cash=net_cash,
            ev_revenue_multiple=ev_rev,
            ev_ebitda_multiple=ev_ebitda,
            p_fcf_multiple=p_fcf,
        )
        result = run_comps(assumptions)
    except Exception as exc:
        return error_result(
            f"failed to run comps valuation: {exc}",
            "provide numeric NTM metrics, share count, net cash, and valuation multiples",
            ["`valuation dcf --revenue ...`", "`valuation sotp --segments ...`"],
            start,
        )

    table: str = build_markdown_table(
        ["method", "implied_ev", "implied_equity", "implied_price"],
        [
            ["EV/Revenue", format_usd(result.ev_revenue_implied_ev), format_usd(result.ev_revenue_implied_equity), format_usd(result.ev_revenue_implied_price, auto_scale=False)],
            ["EV/EBITDA", format_usd(result.ev_ebitda_implied_ev), format_usd(result.ev_ebitda_implied_equity), format_usd(result.ev_ebitda_implied_price, auto_scale=False)],
            ["P/FCF", "N/A", format_usd(result.p_fcf_implied_equity), format_usd(result.p_fcf_implied_price, auto_scale=False)],
        ],
        alignment=["l", "r", "r", "r"],
    )
    output = f"## Comparable Company Valuation\n\n{table}"
    output += maybe_export_text(output, export_path)
    return CommandResult.from_text(output, duration_ms=elapsed_ms(start))
def run_reverse_dcf_command(
    *,
    price: float,
    shares: float,
    net_cash: float,
    base_revenue: float,
    margins_csv: str,
    wacc: float,
    terminal_growth: float,
    years: int = 5,
    export_path: str | None = None,
    settings: HarnessSettings,
) -> CommandResult:
    start: float = time.perf_counter()
    try:
        from minerva.formatting import format_pct, format_usd
        from minerva.valuation import run_reverse_dcf

        result = run_reverse_dcf(
            current_price=price,
            shares_outstanding=shares,
            net_cash=net_cash,
            base_revenue=base_revenue,
            fcf_margin_trajectory=parse_csv_floats(margins_csv),
            wacc=wacc,
            terminal_growth=terminal_growth,
            projection_years=years,
        )
    except Exception as exc:
        return error_result(
            f"failed to run reverse DCF: {exc}",
            "provide numeric inputs and a valid margin trajectory",
            ["`valuation dcf --revenue ...`", "`valuation comps --ntm-revenue ...`"],
            start,
        )

    output = "\n".join(
        [
            "## Reverse DCF",
            "",
            f"current_price: {format_usd(result.current_price, auto_scale=False)}",
            f"implied_revenue_growth: {format_pct(result.implied_revenue_growth * 100)}",
            f"implied_year5_revenue: {format_usd(result.implied_year5_revenue)}",
            f"implied_year5_fcf: {format_usd(result.implied_year5_fcf)}",
            f"assumptions_note: {result.assumptions_note}",
        ]
    )
    output += maybe_export_text(output, export_path)
    return CommandResult.from_text(output, duration_ms=elapsed_ms(start))
def run_sotp_command(
    *,
    segments_spec: str,
    net_cash: float,
    shares: float,
    export_path: str | None = None,
    settings: HarnessSettings,
) -> CommandResult:
    start: float = time.perf_counter()
    try:
        from minerva.formatting import build_markdown_table, format_multiple, format_pct, format_usd
        from minerva.valuation import SOTPSegment, run_sotp

        segments_payload = _load_segments_payload(segments_spec)
        total_revenue: float = sum(float(item["revenue"]) for item in segments_payload) or 1.0
        segments: list[SOTPSegment] = []
        for item in segments_payload:
            revenue: float = float(item["revenue"])
            multiple: float = float(item["ev_revenue_multiple"])
            segments.append(
                SOTPSegment(
                    name=str(item["name"]),
                    revenue=revenue,
                    revenue_pct=float(item.get("revenue_pct", (revenue / total_revenue) * 100)),
                    ev_revenue_multiple=multiple,
                    implied_ev=float(item.get("implied_ev", revenue * multiple)),
                    notes=str(item.get("notes", "")),
                )
            )
        result = run_sotp(segments, net_cash=net_cash, shares_outstanding=shares)
    except Exception as exc:
        return error_result(
            f"failed to run SOTP valuation: {exc}",
            "provide valid inline JSON or a JSON file with segment objects",
            ["`valuation dcf --revenue ...`", "`valuation comps --ntm-revenue ...`"],
            start,
        )

    rows: list[list[str]] = []
    for segment in result.segments:
        rows.append(
            [
                segment.name,
                format_usd(segment.revenue),
                format_pct(segment.revenue_pct),
                format_multiple(segment.ev_revenue_multiple),
                format_usd(segment.implied_ev),
                segment.notes,
            ]
        )
    table = build_markdown_table(
        ["segment", "revenue", "revenue_pct", "ev/revenue", "implied_ev", "notes"],
        rows,
        alignment=["l", "r", "r", "r", "r", "l"],
    )
    output = "\n".join(
        [
            "## Sum-of-the-Parts Valuation",
            "",
            f"total_ev: {format_usd(result.total_ev)}",
            f"equity_value: {format_usd(result.equity_value)}",
            f"price_per_share: {format_usd(result.price_per_share, auto_scale=False)}",
            "",
            table,
        ]
    )
    output += maybe_export_text(output, export_path)
    return CommandResult.from_text(output, duration_ms=elapsed_ms(start))
def run_report_command(
    *,
    ticker: str,
    config_path: str,
    output_path: str,
    settings: HarnessSettings,
) -> CommandResult:
    start: float = time.perf_counter()
    try:
        from minerva.valuation import (
            CompsAssumptions,
            DCFAssumptions,
            SOTPSegment,
            dcf_sensitivity_matrix,
            generate_valuation_report,
            run_comps,
            run_dcf,
            run_reverse_dcf,
            run_sotp,
        )

        config = json.loads(resolve_path(config_path).read_text(encoding="utf-8"))
        dcf_config = config["dcf"]
        comps_config = config["comps"]
        reverse_config = config["reverse_dcf"]
        sotp_config = config["sotp"]

        dcf_assumptions = DCFAssumptions(
            base_revenue=float(dcf_config["revenue"]),
            base_fcf=float(dcf_config.get("fcf", float(dcf_config["revenue"]) * parse_csv_floats(dcf_config["margins"])[0])),
            revenue_growth_rates=parse_csv_floats(dcf_config["growth"]),
            fcf_margins=parse_csv_floats(dcf_config["margins"]),
            wacc=float(dcf_config["wacc"]),
            terminal_growth_rate=float(dcf_config["terminal_growth"]),
            shares_outstanding=float(dcf_config["shares"]),
            net_cash=float(dcf_config["net_cash"]),
            sbc_annual=float(dcf_config.get("sbc", 0.0)),
            sbc_growth_rate=float(dcf_config.get("sbc_growth", 0.0)),
            projection_years=int(dcf_config.get("years", 5)),
        )
        dcf_result = run_dcf(dcf_assumptions)

        comps_assumptions = CompsAssumptions(
            ntm_revenue=float(comps_config["ntm_revenue"]),
            ntm_ebitda=float(comps_config["ntm_ebitda"]),
            ntm_fcf=float(comps_config["ntm_fcf"]),
            shares_outstanding=float(comps_config["shares"]),
            net_cash=float(comps_config["net_cash"]),
            ev_revenue_multiple=float(comps_config["ev_rev"]),
            ev_ebitda_multiple=float(comps_config["ev_ebitda"]),
            p_fcf_multiple=float(comps_config["p_fcf"]),
        )
        comps_result = run_comps(comps_assumptions)

        reverse_result = run_reverse_dcf(
            current_price=float(reverse_config["price"]),
            shares_outstanding=float(reverse_config["shares"]),
            net_cash=float(reverse_config["net_cash"]),
            base_revenue=float(reverse_config["base_revenue"]),
            fcf_margin_trajectory=parse_csv_floats(reverse_config["margins"]),
            wacc=float(reverse_config["wacc"]),
            terminal_growth=float(reverse_config["terminal_growth"]),
            projection_years=int(reverse_config.get("years", 5)),
        )

        sotp_segments = [
            SOTPSegment(
                name=str(item["name"]),
                revenue=float(item["revenue"]),
                revenue_pct=float(item.get("revenue_pct", 0.0)),
                ev_revenue_multiple=float(item["ev_revenue_multiple"]),
                implied_ev=float(item.get("implied_ev", float(item["revenue"]) * float(item["ev_revenue_multiple"]))),
                notes=str(item.get("notes", "")),
            )
            for item in sotp_config["segments"]
        ]
        sotp_result = run_sotp(
            sotp_segments,
            net_cash=float(sotp_config["net_cash"]),
            shares_outstanding=float(sotp_config["shares"]),
        )

        sensitivity_wacc = [float(value) for value in config.get("sensitivity_wacc", [0.09, 0.10, 0.11])]
        sensitivity_tgr = [float(value) for value in config.get("sensitivity_tgr", [0.02, 0.03, 0.04])]
        sensitivity = dcf_sensitivity_matrix(dcf_assumptions, sensitivity_wacc, sensitivity_tgr)

        report = generate_valuation_report(
            ticker=ticker,
            current_price=float(config["current_price"]),
            dcf_result=dcf_result,
            dcf_assumptions=dcf_assumptions,
            comps_result=comps_result,
            comps_assumptions=comps_assumptions,
            reverse_dcf_result=reverse_result,
            sotp_result=sotp_result,
            sensitivity_wacc=sensitivity_wacc,
            sensitivity_tgr=sensitivity_tgr,
            sensitivity_matrix=sensitivity,
        )
        target = resolve_path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(report, encoding="utf-8")
    except Exception as exc:
        return error_result(
            f"failed to generate valuation report: {exc}",
            "provide a valid JSON config file with dcf, comps, reverse_dcf, and sotp sections",
            ["`valuation dcf --revenue ...`", "`valuation report --ticker AAPL --config valuation.json --output valuation.md`"],
            start,
        )

    return CommandResult.from_text(
        f"report_written_to: {str(target)}",
        duration_ms=elapsed_ms(start),
    )
@app.command("dcf", help="Run a discounted cash flow valuation.\n\nExample:\n  minerva valuation dcf --revenue 394e9 --growth 0.06,0.05,0.04 --margins 0.28,0.29,0.30 --wacc 0.10 --terminal-growth 0.03 --shares 15.5e9 --net-cash 57e9")
def dcf_command(
    ctx: typer.Context,
    revenue: float | None = typer.Option(None, "--revenue", help="Base year revenue in USD."),
    growth: str | None = typer.Option(None, "--growth", help="Revenue growth rates as CSV decimals."),
    margins: str | None = typer.Option(None, "--margins", help="FCF margin trajectory as CSV decimals."),
    wacc: float | None = typer.Option(None, "--wacc", help="Weighted average cost of capital."),
    terminal_growth: float | None = typer.Option(None, "--terminal-growth", help="Perpetuity growth rate."),
    shares: float | None = typer.Option(None, "--shares", help="Diluted shares outstanding."),
    net_cash: float | None = typer.Option(None, "--net-cash", help="Cash minus debt in USD."),
    fcf: float | None = typer.Option(None, "--fcf", help="Base year FCF override."),
    sbc: float = typer.Option(0.0, "--sbc", help="Annual stock-based compensation in USD."),
    sbc_growth: float = typer.Option(0.0, "--sbc-growth", help="Annual SBC growth rate."),
    years: int = typer.Option(5, "--years", help="Projection horizon."),
    export: str | None = typer.Option(None, "--export", help="Save full output to file."),
) -> None:
    settings = get_settings()
    if None in {revenue, growth, margins, wacc, terminal_growth, shares, net_cash}:
        abort_with_help(
            ctx,
            what_went_wrong="missing required DCF inputs",
            what_to_do="provide revenue, growth, margins, wacc, terminal growth, shares, and net cash",
            alternatives=["`minerva valuation dcf --revenue 394e9 ...`", "`minerva valuation comps --ntm-revenue 420e9 ...`"],
        )
    _print(
        run_dcf_command(
            revenue=float(revenue),
            fcf=fcf,
            growth_rates_csv=str(growth),
            margins_csv=str(margins),
            wacc=float(wacc),
            terminal_growth=float(terminal_growth),
            shares=float(shares),
            net_cash=float(net_cash),
            sbc=sbc,
            sbc_growth=sbc_growth,
            years=years,
            export_path=export,
            settings=settings,
        )
    )
@app.command("comps", help="Run a comparable company valuation.\n\nExample:\n  minerva valuation comps --ntm-revenue 420e9 --ntm-ebitda 140e9 --ntm-fcf 110e9 --shares 15.5e9 --net-cash 57e9 --ev-rev 8.5 --ev-ebitda 25 --p-fcf 30")
def comps_command(
    ctx: typer.Context,
    ntm_revenue: float | None = typer.Option(None, "--ntm-revenue", help="Next-twelve-months revenue estimate."),
    ntm_ebitda: float | None = typer.Option(None, "--ntm-ebitda", help="NTM EBITDA estimate."),
    ntm_fcf: float | None = typer.Option(None, "--ntm-fcf", help="NTM free cash flow estimate."),
    shares: float | None = typer.Option(None, "--shares", help="Diluted shares outstanding."),
    net_cash: float | None = typer.Option(None, "--net-cash", help="Cash minus debt."),
    ev_rev: float | None = typer.Option(None, "--ev-rev", help="Peer median EV/Revenue multiple."),
    ev_ebitda: float | None = typer.Option(None, "--ev-ebitda", help="Peer median EV/EBITDA multiple."),
    p_fcf: float | None = typer.Option(None, "--p-fcf", help="Peer median P/FCF multiple."),
    export: str | None = typer.Option(None, "--export", help="Save full output to file."),
) -> None:
    settings = get_settings()
    if None in {ntm_revenue, ntm_ebitda, ntm_fcf, shares, net_cash, ev_rev, ev_ebitda, p_fcf}:
        abort_with_help(
            ctx,
            what_went_wrong="missing required comps inputs",
            what_to_do="provide all NTM metrics, capital structure inputs, and peer multiples",
            alternatives=["`minerva valuation comps --ntm-revenue 420e9 ...`", "`minerva valuation dcf --revenue 394e9 ...`"],
        )
    _print(
        run_comps_command(
            ntm_revenue=float(ntm_revenue),
            ntm_ebitda=float(ntm_ebitda),
            ntm_fcf=float(ntm_fcf),
            shares=float(shares),
            net_cash=float(net_cash),
            ev_rev=float(ev_rev),
            ev_ebitda=float(ev_ebitda),
            p_fcf=float(p_fcf),
            export_path=export,
            settings=settings,
        )
    )
@app.command("reverse-dcf", help="Infer the market-implied constant revenue growth rate.\n\nExample:\n  minerva valuation reverse-dcf --price 220 --shares 15.5e9 --net-cash 57e9 --base-revenue 394e9 --margins 0.28,0.29,0.30 --wacc 0.10 --terminal-growth 0.03")
def reverse_dcf_command(
    ctx: typer.Context,
    price: float | None = typer.Option(None, "--price", help="Current share price."),
    shares: float | None = typer.Option(None, "--shares", help="Diluted shares outstanding."),
    net_cash: float | None = typer.Option(None, "--net-cash", help="Cash minus debt."),
    base_revenue: float | None = typer.Option(None, "--base-revenue", help="Most recent annual revenue."),
    margins: str | None = typer.Option(None, "--margins", help="FCF margin trajectory as CSV decimals."),
    wacc: float | None = typer.Option(None, "--wacc", help="Weighted average cost of capital."),
    terminal_growth: float | None = typer.Option(None, "--terminal-growth", help="Perpetuity growth rate."),
    years: int = typer.Option(5, "--years", help="Projection horizon."),
    export: str | None = typer.Option(None, "--export", help="Save full output to file."),
) -> None:
    settings = get_settings()
    if None in {price, shares, net_cash, base_revenue, margins, wacc, terminal_growth}:
        abort_with_help(
            ctx,
            what_went_wrong="missing required reverse DCF inputs",
            what_to_do="provide price, shares, net cash, base revenue, margins, wacc, and terminal growth",
            alternatives=["`minerva valuation reverse-dcf --price 220 ...`", "`minerva valuation dcf --revenue 394e9 ...`"],
        )
    _print(
        run_reverse_dcf_command(
            price=float(price),
            shares=float(shares),
            net_cash=float(net_cash),
            base_revenue=float(base_revenue),
            margins_csv=str(margins),
            wacc=float(wacc),
            terminal_growth=float(terminal_growth),
            years=years,
            export_path=export,
            settings=settings,
        )
    )
@app.command("sotp", help="Run a sum-of-the-parts valuation.\n\nExample:\n  minerva valuation sotp --segments segments.json --net-cash 57e9 --shares 15.5e9")
def sotp_command(
    ctx: typer.Context,
    segments: str | None = typer.Option(None, "--segments", help="JSON array or path to a JSON file."),
    net_cash: float | None = typer.Option(None, "--net-cash", help="Cash minus debt."),
    shares: float | None = typer.Option(None, "--shares", help="Diluted shares outstanding."),
    export: str | None = typer.Option(None, "--export", help="Save full output to file."),
) -> None:
    settings = get_settings()
    if None in {segments, net_cash, shares}:
        abort_with_help(
            ctx,
            what_went_wrong="missing required SOTP inputs",
            what_to_do="provide a segment payload, net cash, and share count",
            alternatives=["`minerva valuation sotp --segments segments.json --net-cash 57e9 --shares 15.5e9`", "`minerva valuation comps --ntm-revenue 420e9 ...`"],
        )
    _print(run_sotp_command(segments_spec=str(segments), net_cash=float(net_cash), shares=float(shares), export_path=export, settings=settings))
@app.command("report", help="Generate a full markdown valuation report.\n\nExample:\n  minerva valuation report --ticker AAPL --config valuation.json --output valuation.md")
def report_command(
    ctx: typer.Context,
    ticker: str | None = typer.Option(None, "--ticker", help="Company ticker."),
    config: str | None = typer.Option(None, "--config", help="JSON file with valuation inputs."),
    output: str | None = typer.Option(None, "--output", help="Output markdown file path."),
) -> None:
    settings = get_settings()
    if None in {ticker, config, output}:
        abort_with_help(
            ctx,
            what_went_wrong="missing required report inputs",
            what_to_do="provide a ticker, JSON config path, and markdown output path",
            alternatives=["`minerva valuation report --ticker AAPL --config valuation.json --output valuation.md`", "`minerva valuation dcf --revenue 394e9 ...`"],
        )
    _print(run_report_command(ticker=str(ticker), config_path=str(config), output_path=str(output), settings=settings))
def _load_segments_payload(segments_spec: str) -> list[dict[str, Any]]:
    try:
        parsed = json.loads(segments_spec)
    except json.JSONDecodeError:
        candidate: Path = resolve_path(segments_spec)
        parsed = json.loads(candidate.read_text(encoding="utf-8"))
    if not isinstance(parsed, list):
        raise ValueError("segments JSON must decode to a list of objects")
    return parsed
def _dispatch_help(subcommand: str, missing: list[str]) -> CommandResult:
    usage: dict[str, str] = {
        "dcf": "valuation dcf --revenue <float> --growth <csv> --margins <csv> --wacc <float> --terminal-growth <float> --shares <float> --net-cash <float> [--fcf <float>] [--export PATH]",
        "comps": "valuation comps --ntm-revenue <float> --ntm-ebitda <float> --ntm-fcf <float> --shares <float> --net-cash <float> --ev-rev <float> --ev-ebitda <float> --p-fcf <float> [--export PATH]",
        "reverse-dcf": "valuation reverse-dcf --price <float> --shares <float> --net-cash <float> --base-revenue <float> --margins <csv> --wacc <float> --terminal-growth <float> [--export PATH]",
        "sotp": "valuation sotp --segments <json-or-path> --net-cash <float> --shares <float> [--export PATH]",
        "report": "valuation report --ticker <ticker> --config <json-file> --output <markdown-file>",
    }
    return CommandResult.from_text(
        "",
        stderr=_usage_error(
            f"missing required arguments for `valuation {subcommand}`: {', '.join(missing)}",
            usage[subcommand],
            ["`valuation dcf --revenue 394e9 ...`", "`valuation report --ticker AAPL --config valuation.json --output valuation.md`"],
            VALUATION_HELP,
        ),
        exit_code=1,
    )
def _usage_error(what: str, what_to_do: str, alternatives: list[str], help_text: str) -> str:
    return "\n".join(
        [
            f"What went wrong: {what}",
            f"What to do instead: {what_to_do}",
            f"Available alternatives: {', '.join(alternatives)}",
            "",
            help_text.rstrip(),
        ]
    )
def _print(result: CommandResult) -> None:
    envelope = OutputEnvelope.from_result(result, workspace_root=get_settings().ensure_workspace_root())
    typer.echo(envelope.render())
