"""Valuation commands."""

from __future__ import annotations

import json
import time
from pathlib import Path

import typer

from harness.commands.common import elapsed_ms, error_result
from harness.commands.fs import resolve_workspace_path
from harness.config import HarnessSettings, get_settings
from harness.output import CommandResult, OutputEnvelope
from minerva.formatting import build_markdown_table, format_pct, format_usd
from minerva.valuation import (
    CompsAssumptions,
    DCFAssumptions,
    SOTPSegment,
    run_comps,
    run_dcf,
    run_reverse_dcf,
    run_sotp,
)

app = typer.Typer(help="Valuation commands.", no_args_is_help=True)


def dispatch(args: list[str], settings: HarnessSettings | None = None) -> CommandResult:
    active_settings: HarnessSettings = settings or get_settings()
    if not args:
        return _usage_error(
            "valuation",
            "Usage: valuation <dcf|comps|reverse-dcf|sotp> ...",
            ["valuation dcf --revenue ...", "valuation comps --ntm-revenue ..."],
        )

    subcommand: str = args[0]
    try:
        parsed: dict[str, str] = _parse_flag_args(args[1:])
    except ValueError as exc:
        return CommandResult.from_text("", stderr=str(exc), exit_code=1)

    if subcommand == "dcf":
        required = ["revenue", "fcf", "growth", "margins", "wacc", "terminal-growth", "shares", "net-cash"]
        missing = [name for name in required if name not in parsed]
        if missing:
            return _usage_error("valuation dcf", "Usage: valuation dcf --revenue <f> --fcf <f> ...", ["valuation comps --ntm-revenue <f>"])
        return run_dcf_command(
            revenue=float(parsed["revenue"]),
            fcf=float(parsed["fcf"]),
            growth_rates_csv=parsed["growth"],
            margins_csv=parsed["margins"],
            wacc=float(parsed["wacc"]),
            terminal_growth=float(parsed["terminal-growth"]),
            shares=float(parsed["shares"]),
            net_cash=float(parsed["net-cash"]),
            sbc=float(parsed.get("sbc", 0.0)),
            sbc_growth=float(parsed.get("sbc-growth", 0.0)),
            years=int(parsed.get("years", 5)),
            settings=active_settings,
        )
    if subcommand == "comps":
        required = ["ntm-revenue", "ntm-ebitda", "ntm-fcf", "shares", "net-cash", "ev-rev", "ev-ebitda", "p-fcf"]
        missing = [name for name in required if name not in parsed]
        if missing:
            return _usage_error("valuation comps", "Usage: valuation comps --ntm-revenue <f> --ntm-ebitda <f> ...", ["valuation dcf --revenue <f>"])
        return run_comps_command(
            ntm_revenue=float(parsed["ntm-revenue"]),
            ntm_ebitda=float(parsed["ntm-ebitda"]),
            ntm_fcf=float(parsed["ntm-fcf"]),
            shares=float(parsed["shares"]),
            net_cash=float(parsed["net-cash"]),
            ev_rev=float(parsed["ev-rev"]),
            ev_ebitda=float(parsed["ev-ebitda"]),
            p_fcf=float(parsed["p-fcf"]),
            settings=active_settings,
        )
    if subcommand == "reverse-dcf":
        required = ["price", "shares", "net-cash", "base-revenue", "margins", "wacc", "terminal-growth"]
        missing = [name for name in required if name not in parsed]
        if missing:
            return _usage_error("valuation reverse-dcf", "Usage: valuation reverse-dcf --price <f> --shares <f> ...", ["valuation dcf --revenue <f>"])
        return run_reverse_dcf_command(
            price=float(parsed["price"]),
            shares=float(parsed["shares"]),
            net_cash=float(parsed["net-cash"]),
            base_revenue=float(parsed["base-revenue"]),
            margins_csv=parsed["margins"],
            wacc=float(parsed["wacc"]),
            terminal_growth=float(parsed["terminal-growth"]),
            years=int(parsed.get("years", 5)),
            settings=active_settings,
        )
    if subcommand == "sotp":
        required = ["segments", "net-cash", "shares"]
        missing = [name for name in required if name not in parsed]
        if missing:
            return _usage_error("valuation sotp", "Usage: valuation sotp --segments <json> --net-cash <f> --shares <f>", ["valuation dcf --revenue <f>"])
        return run_sotp_command(
            segments_spec=parsed["segments"],
            net_cash=float(parsed["net-cash"]),
            shares=float(parsed["shares"]),
            settings=active_settings,
        )
    return _usage_error("valuation", f"Unknown valuation subcommand: {subcommand}", ["valuation dcf --revenue <f>"])


def run_dcf_command(
    *,
    revenue: float,
    fcf: float,
    growth_rates_csv: str,
    margins_csv: str,
    wacc: float,
    terminal_growth: float,
    shares: float,
    net_cash: float,
    sbc: float = 0.0,
    sbc_growth: float = 0.0,
    years: int = 5,
    settings: HarnessSettings | None = None,
) -> CommandResult:
    start: float = time.perf_counter()
    _ = settings or get_settings()
    try:
        assumptions = DCFAssumptions(
            base_revenue=revenue,
            base_fcf=fcf,
            revenue_growth_rates=_parse_float_csv(growth_rates_csv),
            fcf_margins=_parse_float_csv(margins_csv),
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
            f"What went wrong: failed to run DCF: {exc}\n"
            "What to do instead: provide numeric inputs and equal-length growth or margin trajectories when possible.\n"
            "Available alternatives: `valuation comps ...`, `valuation reverse-dcf ...`",
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
    table: str = build_markdown_table(
        ["year", "revenue", "growth", "fcf", "fcf_margin", "discount_factor", "pv_fcf"],
        rows,
        alignment=["r", "r", "r", "r", "r", "r", "r"],
    )
    summary: str = "\n".join(
        [
            f"enterprise_value: {format_usd(result.enterprise_value)}",
            f"equity_value: {format_usd(result.equity_value)}",
            f"equity_value_ex_sbc: {format_usd(result.equity_value_ex_sbc)}",
            f"price_per_share: {format_usd(result.price_per_share, auto_scale=False)}",
            f"price_per_share_ex_sbc: {format_usd(result.price_per_share_ex_sbc, auto_scale=False)}",
        ]
    )
    return CommandResult.from_text(f"{summary}\n\n{table}", duration_ms=elapsed_ms(start))


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
    settings: HarnessSettings | None = None,
) -> CommandResult:
    start: float = time.perf_counter()
    _ = settings or get_settings()
    try:
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
            f"What went wrong: failed to run comps valuation: {exc}\n"
            "What to do instead: provide numeric NTM metrics, share count, net cash, and valuation multiples.\n"
            "Available alternatives: `valuation dcf ...`, `valuation sotp ...`",
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
    return CommandResult.from_text(table, duration_ms=elapsed_ms(start))


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
    settings: HarnessSettings | None = None,
) -> CommandResult:
    start: float = time.perf_counter()
    _ = settings or get_settings()
    try:
        result = run_reverse_dcf(
            current_price=price,
            shares_outstanding=shares,
            net_cash=net_cash,
            base_revenue=base_revenue,
            fcf_margin_trajectory=_parse_float_csv(margins_csv),
            wacc=wacc,
            terminal_growth=terminal_growth,
            projection_years=years,
        )
    except Exception as exc:
        return error_result(
            f"What went wrong: failed to run reverse DCF: {exc}\n"
            "What to do instead: provide numeric inputs and a valid margin trajectory.\n"
            "Available alternatives: `valuation dcf ...`, `valuation comps ...`",
            start,
        )

    lines: list[str] = [
        f"current_price: {format_usd(result.current_price, auto_scale=False)}",
        f"implied_revenue_growth: {format_pct(result.implied_revenue_growth * 100)}",
        f"implied_year5_revenue: {format_usd(result.implied_year5_revenue)}",
        f"implied_year5_fcf: {format_usd(result.implied_year5_fcf)}",
        f"assumptions_note: {result.assumptions_note}",
    ]
    return CommandResult.from_text("\n".join(lines), duration_ms=elapsed_ms(start))


def run_sotp_command(
    *,
    segments_spec: str,
    net_cash: float,
    shares: float,
    settings: HarnessSettings | None = None,
) -> CommandResult:
    start: float = time.perf_counter()
    active_settings: HarnessSettings = settings or get_settings()
    try:
        segments_payload = _load_segments_payload(segments_spec, active_settings)
        total_revenue: float = sum(float(item["revenue"]) for item in segments_payload) or 1.0
        segments: list[SOTPSegment] = []
        for item in segments_payload:
            revenue: float = float(item["revenue"])
            multiple: float = float(item["ev_revenue_multiple"])
            implied_ev: float = float(item.get("implied_ev", revenue * multiple))
            revenue_pct: float = float(item.get("revenue_pct", (revenue / total_revenue) * 100))
            segments.append(
                SOTPSegment(
                    name=str(item["name"]),
                    revenue=revenue,
                    revenue_pct=revenue_pct,
                    ev_revenue_multiple=multiple,
                    implied_ev=implied_ev,
                    notes=str(item.get("notes", "")),
                )
            )
        result = run_sotp(segments, net_cash=net_cash, shares_outstanding=shares)
    except Exception as exc:
        return error_result(
            f"What went wrong: failed to run SOTP valuation: {exc}\n"
            "What to do instead: provide valid JSON inline or a JSON file with segment objects.\n"
            "Available alternatives: `valuation dcf ...`, `valuation comps ...`",
            start,
        )

    rows: list[list[str]] = []
    for segment in result.segments:
        rows.append(
            [
                segment.name,
                format_usd(segment.revenue),
                format_pct(segment.revenue_pct),
                f"{segment.ev_revenue_multiple:.1f}x",
                format_usd(segment.implied_ev),
                segment.notes,
            ]
        )
    table = build_markdown_table(
        ["segment", "revenue", "revenue_pct", "ev/revenue", "implied_ev", "notes"],
        rows,
        alignment=["l", "r", "r", "r", "r", "l"],
    )
    summary = "\n".join(
        [
            f"total_ev: {format_usd(result.total_ev)}",
            f"equity_value: {format_usd(result.equity_value)}",
            f"price_per_share: {format_usd(result.price_per_share, auto_scale=False)}",
        ]
    )
    return CommandResult.from_text(f"{summary}\n\n{table}", duration_ms=elapsed_ms(start))


@app.command("dcf")
def dcf_command(
    revenue: float = typer.Option(..., "--revenue"),
    fcf: float = typer.Option(..., "--fcf"),
    growth: str = typer.Option(..., "--growth"),
    margins: str = typer.Option(..., "--margins"),
    wacc: float = typer.Option(..., "--wacc"),
    terminal_growth: float = typer.Option(..., "--terminal-growth"),
    shares: float = typer.Option(..., "--shares"),
    net_cash: float = typer.Option(..., "--net-cash"),
    sbc: float = typer.Option(0.0, "--sbc"),
    sbc_growth: float = typer.Option(0.0, "--sbc-growth"),
    years: int = typer.Option(5, "--years"),
) -> None:
    """Run a discounted cash flow valuation."""
    _print(
        run_dcf_command(
            revenue=revenue,
            fcf=fcf,
            growth_rates_csv=growth,
            margins_csv=margins,
            wacc=wacc,
            terminal_growth=terminal_growth,
            shares=shares,
            net_cash=net_cash,
            sbc=sbc,
            sbc_growth=sbc_growth,
            years=years,
        )
    )


@app.command("comps")
def comps_command(
    ntm_revenue: float = typer.Option(..., "--ntm-revenue"),
    ntm_ebitda: float = typer.Option(..., "--ntm-ebitda"),
    ntm_fcf: float = typer.Option(..., "--ntm-fcf"),
    shares: float = typer.Option(..., "--shares"),
    net_cash: float = typer.Option(..., "--net-cash"),
    ev_rev: float = typer.Option(..., "--ev-rev"),
    ev_ebitda: float = typer.Option(..., "--ev-ebitda"),
    p_fcf: float = typer.Option(..., "--p-fcf"),
) -> None:
    """Run a comparable company valuation."""
    _print(
        run_comps_command(
            ntm_revenue=ntm_revenue,
            ntm_ebitda=ntm_ebitda,
            ntm_fcf=ntm_fcf,
            shares=shares,
            net_cash=net_cash,
            ev_rev=ev_rev,
            ev_ebitda=ev_ebitda,
            p_fcf=p_fcf,
        )
    )


@app.command("reverse-dcf")
def reverse_dcf_command(
    price: float = typer.Option(..., "--price"),
    shares: float = typer.Option(..., "--shares"),
    net_cash: float = typer.Option(..., "--net-cash"),
    base_revenue: float = typer.Option(..., "--base-revenue"),
    margins: str = typer.Option(..., "--margins"),
    wacc: float = typer.Option(..., "--wacc"),
    terminal_growth: float = typer.Option(..., "--terminal-growth"),
    years: int = typer.Option(5, "--years"),
) -> None:
    """Infer implied revenue growth from the current stock price."""
    _print(
        run_reverse_dcf_command(
            price=price,
            shares=shares,
            net_cash=net_cash,
            base_revenue=base_revenue,
            margins_csv=margins,
            wacc=wacc,
            terminal_growth=terminal_growth,
            years=years,
        )
    )


@app.command("sotp")
def sotp_command(
    segments: str = typer.Option(..., "--segments"),
    net_cash: float = typer.Option(..., "--net-cash"),
    shares: float = typer.Option(..., "--shares"),
) -> None:
    """Run a sum-of-the-parts valuation."""
    _print(run_sotp_command(segments_spec=segments, net_cash=net_cash, shares=shares))


def _parse_flag_args(args: list[str]) -> dict[str, str]:
    parsed: dict[str, str] = {}
    index: int = 0
    while index < len(args):
        token: str = args[index]
        if not token.startswith("--") or index + 1 >= len(args):
            raise ValueError(
                "Invalid valuation arguments.\n"
                "What to do instead: pass values as `--name value` pairs.\n"
                "Available alternatives: `valuation dcf --revenue ...`, `valuation comps --ntm-revenue ...`"
            )
        parsed[token.removeprefix("--")] = args[index + 1]
        index += 2
    return parsed


def _parse_float_csv(raw: str) -> list[float]:
    return [float(item.strip()) for item in raw.split(",") if item.strip()]


def _load_segments_payload(segments_spec: str, settings: HarnessSettings) -> list[dict]:
    candidate: Path = resolve_workspace_path(segments_spec, settings)
    payload: str
    if candidate.exists() and candidate.is_file():
        payload = candidate.read_text(encoding="utf-8")
    else:
        payload = segments_spec
    parsed = json.loads(payload)
    if not isinstance(parsed, list):
        raise ValueError("segments JSON must decode to a list of objects")
    return parsed


def _usage_error(command: str, usage: str, alternatives: list[str]) -> CommandResult:
    return CommandResult.from_text(
        "",
        stderr=(
            f"Invalid invocation for `{command}`.\n"
            f"What to do instead: {usage}\n"
            f"Available alternatives: {', '.join(alternatives)}"
        ),
        exit_code=1,
    )


def _print(result: CommandResult) -> None:
    envelope = OutputEnvelope.from_result(result, workspace_root=get_settings().ensure_workspace_root())
    typer.echo(envelope.render())
