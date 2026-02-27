"""Valuation models and calculation engine for equity analysis.

Supports DCF, comparable company analysis, reverse DCF, and sum-of-the-parts.
"""

from pydantic import BaseModel, Field

from minerva.formatting import (
    build_markdown_table,
    format_multiple,
    format_pct,
    format_usd,
)


# ---------------------------------------------------------------------------
# Pydantic Models
# ---------------------------------------------------------------------------


class DCFAssumptions(BaseModel):
    """All inputs for a discounted cash flow valuation."""

    base_revenue: float = Field(description="Base year revenue in USD")
    base_fcf: float = Field(description="Base year free cash flow in USD")
    revenue_growth_rates: list[float] = Field(
        description="Annual revenue growth rates as decimals (e.g. 0.18 for 18%)"
    )
    fcf_margins: list[float] = Field(
        description="FCF margin for each projection year as decimals"
    )
    wacc: float = Field(description="Weighted avg cost of capital as decimal")
    terminal_growth_rate: float = Field(description="Perpetuity growth rate as decimal")
    shares_outstanding: float = Field(description="Diluted shares outstanding")
    net_cash: float = Field(description="Cash minus debt (positive = net cash)")
    sbc_annual: float = Field(default=0.0, description="Annual SBC to subtract as real cost")
    sbc_growth_rate: float = Field(default=0.0, description="Annual SBC growth rate as decimal")
    projection_years: int = Field(default=5)


class DCFProjectionYear(BaseModel):
    """Single year of DCF projection."""

    year: int
    revenue: float
    revenue_growth: float
    fcf: float
    fcf_margin: float
    discount_factor: float
    pv_fcf: float
    sbc: float
    pv_sbc: float


class DCFResult(BaseModel):
    """Complete DCF output."""

    projections: list[DCFProjectionYear]
    terminal_fcf: float
    terminal_value: float
    pv_terminal_value: float
    pv_total_fcf: float
    pv_total_sbc: float
    enterprise_value: float
    equity_value: float
    price_per_share: float
    equity_value_ex_sbc: float
    price_per_share_ex_sbc: float


class CompsAssumptions(BaseModel):
    """Inputs for comparable company analysis."""

    ntm_revenue: float
    ntm_ebitda: float
    ntm_fcf: float
    shares_outstanding: float
    net_cash: float
    ev_revenue_multiple: float = Field(description="Peer median EV/Revenue")
    ev_ebitda_multiple: float = Field(description="Peer median EV/EBITDA")
    p_fcf_multiple: float = Field(description="Peer median P/FCF")


class CompsResult(BaseModel):
    """Implied valuations from peer multiples."""

    ev_revenue_implied_ev: float
    ev_revenue_implied_equity: float
    ev_revenue_implied_price: float
    ev_ebitda_implied_ev: float
    ev_ebitda_implied_equity: float
    ev_ebitda_implied_price: float
    p_fcf_implied_equity: float
    p_fcf_implied_price: float


class ReverseDCFResult(BaseModel):
    """What the market is implying at the current price."""

    current_price: float
    implied_revenue_growth: float = Field(description="Constant annual growth rate implied")
    implied_year5_revenue: float
    implied_year5_fcf: float
    assumptions_note: str


class SOTPSegment(BaseModel):
    """Single segment in a sum-of-the-parts valuation."""

    name: str
    revenue: float
    revenue_pct: float = Field(description="Percentage of total revenue (0-100)")
    ev_revenue_multiple: float
    implied_ev: float
    notes: str = ""


class SOTPResult(BaseModel):
    """Sum-of-the-parts valuation output."""

    segments: list[SOTPSegment]
    total_ev: float
    net_cash: float
    equity_value: float
    shares_outstanding: float
    price_per_share: float


# ---------------------------------------------------------------------------
# Calculation Functions
# ---------------------------------------------------------------------------


def run_dcf(assumptions: DCFAssumptions) -> DCFResult:
    """Run a discounted cash flow valuation."""
    a: DCFAssumptions = assumptions
    projections: list[DCFProjectionYear] = []
    revenue: float = a.base_revenue
    sbc: float = a.sbc_annual
    pv_total_fcf: float = 0.0
    pv_total_sbc: float = 0.0

    for i in range(a.projection_years):
        growth: float = a.revenue_growth_rates[i] if i < len(a.revenue_growth_rates) else a.revenue_growth_rates[-1]
        margin: float = a.fcf_margins[i] if i < len(a.fcf_margins) else a.fcf_margins[-1]

        revenue = revenue * (1 + growth)
        fcf: float = revenue * margin
        sbc = sbc * (1 + a.sbc_growth_rate)
        discount_factor: float = 1 / (1 + a.wacc) ** (i + 1)
        pv_fcf: float = fcf * discount_factor
        pv_sbc: float = sbc * discount_factor

        pv_total_fcf += pv_fcf
        pv_total_sbc += pv_sbc

        projections.append(DCFProjectionYear(
            year=i + 1,
            revenue=revenue,
            revenue_growth=growth,
            fcf=fcf,
            fcf_margin=margin,
            discount_factor=discount_factor,
            pv_fcf=pv_fcf,
            sbc=sbc,
            pv_sbc=pv_sbc,
        ))

    terminal_fcf: float = projections[-1].fcf * (1 + a.terminal_growth_rate)
    terminal_value: float = terminal_fcf / (a.wacc - a.terminal_growth_rate)
    terminal_discount: float = 1 / (1 + a.wacc) ** a.projection_years
    pv_terminal: float = terminal_value * terminal_discount

    enterprise_value: float = pv_total_fcf + pv_terminal
    equity_value: float = enterprise_value + a.net_cash
    price_per_share: float = equity_value / a.shares_outstanding

    equity_value_ex_sbc: float = equity_value - pv_total_sbc
    price_per_share_ex_sbc: float = equity_value_ex_sbc / a.shares_outstanding

    return DCFResult(
        projections=projections,
        terminal_fcf=terminal_fcf,
        terminal_value=terminal_value,
        pv_terminal_value=pv_terminal,
        pv_total_fcf=pv_total_fcf,
        pv_total_sbc=pv_total_sbc,
        enterprise_value=enterprise_value,
        equity_value=equity_value,
        price_per_share=price_per_share,
        equity_value_ex_sbc=equity_value_ex_sbc,
        price_per_share_ex_sbc=price_per_share_ex_sbc,
    )


def run_comps(assumptions: CompsAssumptions) -> CompsResult:
    """Run comparable company valuation analysis."""
    a: CompsAssumptions = assumptions

    ev_rev: float = a.ntm_revenue * a.ev_revenue_multiple
    ev_ebitda: float = a.ntm_ebitda * a.ev_ebitda_multiple
    p_fcf_equity: float = a.ntm_fcf * a.p_fcf_multiple

    return CompsResult(
        ev_revenue_implied_ev=ev_rev,
        ev_revenue_implied_equity=ev_rev + a.net_cash,
        ev_revenue_implied_price=(ev_rev + a.net_cash) / a.shares_outstanding,
        ev_ebitda_implied_ev=ev_ebitda,
        ev_ebitda_implied_equity=ev_ebitda + a.net_cash,
        ev_ebitda_implied_price=(ev_ebitda + a.net_cash) / a.shares_outstanding,
        p_fcf_implied_equity=p_fcf_equity,
        p_fcf_implied_price=p_fcf_equity / a.shares_outstanding,
    )


def run_reverse_dcf(
    current_price: float,
    shares_outstanding: float,
    net_cash: float,
    base_revenue: float,
    fcf_margin_trajectory: list[float],
    wacc: float,
    terminal_growth: float,
    projection_years: int = 5,
) -> ReverseDCFResult:
    """Find the constant revenue growth rate implied by the current stock price.

    Uses bisection search to solve for the growth rate.
    """
    target_equity: float = current_price * shares_outstanding
    target_ev: float = target_equity - net_cash

    def _ev_for_growth(g: float) -> float:
        rev: float = base_revenue
        pv_fcf: float = 0.0
        last_fcf: float = 0.0
        for i in range(projection_years):
            rev = rev * (1 + g)
            margin: float = fcf_margin_trajectory[i] if i < len(fcf_margin_trajectory) else fcf_margin_trajectory[-1]
            fcf: float = rev * margin
            pv_fcf += fcf / (1 + wacc) ** (i + 1)
            last_fcf = fcf
        tv: float = last_fcf * (1 + terminal_growth) / (wacc - terminal_growth)
        pv_tv: float = tv / (1 + wacc) ** projection_years
        return pv_fcf + pv_tv

    low: float = -0.10
    high: float = 0.80
    mid: float = 0.0
    for _ in range(100):
        mid = (low + high) / 2
        ev_mid: float = _ev_for_growth(mid)
        if abs(ev_mid - target_ev) < 1e6:
            break
        if ev_mid < target_ev:
            low = mid
        else:
            high = mid

    implied_growth: float = mid
    final_rev: float = base_revenue * (1 + implied_growth) ** projection_years
    final_margin: float = fcf_margin_trajectory[-1] if fcf_margin_trajectory else 0.10
    final_fcf: float = final_rev * final_margin

    return ReverseDCFResult(
        current_price=current_price,
        implied_revenue_growth=implied_growth,
        implied_year5_revenue=final_rev,
        implied_year5_fcf=final_fcf,
        assumptions_note=(
            f"Assumes FCF margins expanding to {final_margin:.0%} by year {projection_years}, "
            f"WACC={wacc:.1%}, terminal growth={terminal_growth:.1%}"
        ),
    )


def run_sotp(
    segments: list[SOTPSegment],
    net_cash: float,
    shares_outstanding: float,
) -> SOTPResult:
    """Run sum-of-the-parts valuation from pre-built segments."""
    total_ev: float = sum(s.implied_ev for s in segments)
    equity_value: float = total_ev + net_cash

    return SOTPResult(
        segments=segments,
        total_ev=total_ev,
        net_cash=net_cash,
        equity_value=equity_value,
        shares_outstanding=shares_outstanding,
        price_per_share=equity_value / shares_outstanding,
    )


# ---------------------------------------------------------------------------
# Sensitivity Analysis
# ---------------------------------------------------------------------------


def dcf_sensitivity_matrix(
    assumptions: DCFAssumptions,
    wacc_range: list[float],
    tgr_range: list[float],
) -> list[list[float]]:
    """Generate a WACC vs terminal growth rate sensitivity matrix.

    Returns a 2D list of price-per-share values (with SBC haircut).
    Rows = WACC values, Columns = terminal growth rate values.
    """
    matrix: list[list[float]] = []
    for w in wacc_range:
        row: list[float] = []
        for g in tgr_range:
            tweaked: DCFAssumptions = assumptions.model_copy(
                update={"wacc": w, "terminal_growth_rate": g}
            )
            result: DCFResult = run_dcf(tweaked)
            row.append(result.price_per_share_ex_sbc)
        matrix.append(row)
    return matrix


# ---------------------------------------------------------------------------
# Report Generator
# ---------------------------------------------------------------------------


def generate_valuation_report(
    ticker: str,
    current_price: float,
    dcf_result: DCFResult,
    dcf_assumptions: DCFAssumptions,
    comps_result: CompsResult,
    comps_assumptions: CompsAssumptions,
    reverse_dcf_result: ReverseDCFResult,
    sotp_result: SOTPResult,
    sensitivity_wacc: list[float],
    sensitivity_tgr: list[float],
    sensitivity_matrix: list[list[float]],
) -> str:
    """Generate a complete valuation report in markdown."""
    sections: list[str] = [
        f"# {ticker} — Valuation Analysis",
        "",
        f"**Current Price**: ${current_price:.2f}",
        "",
        "---",
        "",
        _section_dcf_assumptions(dcf_assumptions),
        _section_dcf_projections(dcf_result),
        _section_dcf_summary(dcf_result, dcf_assumptions),
        _section_sensitivity(sensitivity_wacc, sensitivity_tgr, sensitivity_matrix),
        _section_comps(comps_result, comps_assumptions),
        _section_reverse_dcf(reverse_dcf_result),
        _section_sotp(sotp_result),
        _section_valuation_summary(
            ticker, current_price, dcf_result, comps_result, sotp_result
        ),
        _section_football_field(
            current_price, dcf_result, comps_result, sotp_result
        ),
        "",
        "---",
        "*Generated by Minerva valuation engine.*",
    ]
    return "\n".join(sections)


# ---------------------------------------------------------------------------
# Report Section Helpers
# ---------------------------------------------------------------------------


def _section_dcf_assumptions(a: DCFAssumptions) -> str:
    rows: list[list[str]] = [
        ["Base Revenue", format_usd(a.base_revenue)],
        ["Base FCF", format_usd(a.base_fcf)],
        ["WACC", format_pct(a.wacc * 100)],
        ["Terminal Growth", format_pct(a.terminal_growth_rate * 100)],
        ["Projection Years", str(a.projection_years)],
        ["Diluted Shares", f"{a.shares_outstanding / 1e6:.0f}M"],
        ["Net Cash", format_usd(a.net_cash)],
        ["Annual SBC (base)", format_usd(a.sbc_annual)],
        [
            "Revenue Growth Path",
            " → ".join(format_pct(g * 100) for g in a.revenue_growth_rates),
        ],
        [
            "FCF Margin Path",
            " → ".join(format_pct(m * 100) for m in a.fcf_margins),
        ],
    ]
    table: str = build_markdown_table(
        ["Assumption", "Value"], rows, alignment=["l", "r"]
    )
    return f"## 1. DCF — Conservative Assumptions\n\n{table}\n"


def _section_dcf_projections(r: DCFResult) -> str:
    headers: list[str] = [
        "Year", "Revenue", "Growth", "FCF", "FCF Margin",
        "SBC", "Discount Factor", "PV(FCF)", "PV(SBC)",
    ]
    rows: list[list[str]] = []
    for p in r.projections:
        rows.append([
            f"Y{p.year}",
            format_usd(p.revenue),
            format_pct(p.revenue_growth * 100),
            format_usd(p.fcf),
            format_pct(p.fcf_margin * 100),
            format_usd(p.sbc),
            f"{p.discount_factor:.4f}",
            format_usd(p.pv_fcf),
            format_usd(p.pv_sbc),
        ])
    alignment: list[str] = ["l"] + ["r"] * (len(headers) - 1)
    table: str = build_markdown_table(headers, rows, alignment=alignment)
    return f"## 2. DCF — 5-Year Projection\n\n{table}\n"


def _section_dcf_summary(r: DCFResult, a: DCFAssumptions) -> str:
    rows: list[list[str]] = [
        ["PV of Projected FCFs", format_usd(r.pv_total_fcf)],
        ["Terminal FCF", format_usd(r.terminal_fcf)],
        ["Terminal Value (undiscounted)", format_usd(r.terminal_value)],
        ["PV of Terminal Value", format_usd(r.pv_terminal_value)],
        ["**Enterprise Value**", f"**{format_usd(r.enterprise_value)}**"],
        ["+ Net Cash", format_usd(a.net_cash)],
        ["**Equity Value**", f"**{format_usd(r.equity_value)}**"],
        ["Shares Outstanding", f"{a.shares_outstanding / 1e6:.0f}M"],
        ["**Price per Share**", f"**${r.price_per_share:.2f}**"],
        ["", ""],
        ["PV of Projected SBC", f"({format_usd(r.pv_total_sbc)})"],
        ["Equity Value (ex-SBC)", format_usd(r.equity_value_ex_sbc)],
        ["**Price per Share (ex-SBC)**", f"**${r.price_per_share_ex_sbc:.2f}**"],
    ]
    table: str = build_markdown_table(
        ["Metric", "Value"], rows, alignment=["l", "r"]
    )
    return f"## 3. DCF — Valuation Bridge\n\n{table}\n"


def _section_sensitivity(
    wacc_range: list[float],
    tgr_range: list[float],
    matrix: list[list[float]],
) -> str:
    headers: list[str] = ["WACC \\ TGR"] + [format_pct(g * 100) for g in tgr_range]
    rows: list[list[str]] = []
    for i, w in enumerate(wacc_range):
        row: list[str] = [f"**{format_pct(w * 100)}**"]
        for price in matrix[i]:
            row.append(f"${price:.2f}")
        rows.append(row)
    alignment: list[str] = ["l"] + ["r"] * len(tgr_range)
    table: str = build_markdown_table(headers, rows, alignment=alignment)
    return f"## 4. Sensitivity Analysis — Price per Share (ex-SBC)\n\n{table}\n"


def _section_comps(r: CompsResult, a: CompsAssumptions) -> str:
    rows: list[list[str]] = [
        [
            "EV/Revenue",
            format_multiple(a.ev_revenue_multiple),
            format_usd(a.ntm_revenue),
            format_usd(r.ev_revenue_implied_ev),
            format_usd(r.ev_revenue_implied_equity),
            f"${r.ev_revenue_implied_price:.2f}",
        ],
        [
            "EV/EBITDA",
            format_multiple(a.ev_ebitda_multiple),
            format_usd(a.ntm_ebitda),
            format_usd(r.ev_ebitda_implied_ev),
            format_usd(r.ev_ebitda_implied_equity),
            f"${r.ev_ebitda_implied_price:.2f}",
        ],
        [
            "P/FCF",
            format_multiple(a.p_fcf_multiple),
            format_usd(a.ntm_fcf),
            "—",
            format_usd(r.p_fcf_implied_equity),
            f"${r.p_fcf_implied_price:.2f}",
        ],
    ]
    headers: list[str] = [
        "Metric", "Peer Multiple", "NTM Base", "Implied EV", "Implied Equity", "Price/Share",
    ]
    alignment: list[str] = ["l", "r", "r", "r", "r", "r"]
    table: str = build_markdown_table(headers, rows, alignment=alignment)
    return f"## 5. Comparable Company Analysis\n\n{table}\n"


def _section_reverse_dcf(r: ReverseDCFResult) -> str:
    rows: list[list[str]] = [
        ["Current Price", f"${r.current_price:.2f}"],
        ["Implied Constant Revenue Growth", format_pct(r.implied_revenue_growth * 100)],
        ["Implied Year-5 Revenue", format_usd(r.implied_year5_revenue)],
        ["Implied Year-5 FCF", format_usd(r.implied_year5_fcf)],
    ]
    table: str = build_markdown_table(
        ["Metric", "Value"], rows, alignment=["l", "r"]
    )
    return f"## 6. Reverse DCF — What the Market Implies\n\n{table}\n\n*{r.assumptions_note}*\n"


def _section_sotp(r: SOTPResult) -> str:
    headers: list[str] = [
        "Segment", "Revenue", "% of Total", "EV/Revenue", "Implied EV", "Notes",
    ]
    rows: list[list[str]] = []
    for s in r.segments:
        rows.append([
            f"**{s.name}**",
            format_usd(s.revenue),
            format_pct(s.revenue_pct),
            format_multiple(s.ev_revenue_multiple),
            format_usd(s.implied_ev),
            s.notes,
        ])
    rows.append(["**Total EV**", "", "", "", f"**{format_usd(r.total_ev)}**", ""])
    rows.append(["+ Net Cash", "", "", "", format_usd(r.net_cash), ""])
    rows.append([
        "**Equity Value**", "", "", "", f"**{format_usd(r.equity_value)}**", "",
    ])
    rows.append([
        "**Price/Share**", "", "", "", f"**${r.price_per_share:.2f}**", "",
    ])
    alignment: list[str] = ["l", "r", "r", "r", "r", "l"]
    table: str = build_markdown_table(headers, rows, alignment=alignment)
    return f"## 7. Sum-of-the-Parts (SOTP)\n\n{table}\n"


def _section_valuation_summary(
    ticker: str,
    current_price: float,
    dcf: DCFResult,
    comps: CompsResult,
    sotp: SOTPResult,
) -> str:
    rows: list[list[str]] = [
        ["DCF (ex-SBC)", f"${dcf.price_per_share_ex_sbc:.2f}", _upside(current_price, dcf.price_per_share_ex_sbc)],
        ["DCF (pre-SBC)", f"${dcf.price_per_share:.2f}", _upside(current_price, dcf.price_per_share)],
        ["Comps — EV/Revenue", f"${comps.ev_revenue_implied_price:.2f}", _upside(current_price, comps.ev_revenue_implied_price)],
        ["Comps — EV/EBITDA", f"${comps.ev_ebitda_implied_price:.2f}", _upside(current_price, comps.ev_ebitda_implied_price)],
        ["Comps — P/FCF", f"${comps.p_fcf_implied_price:.2f}", _upside(current_price, comps.p_fcf_implied_price)],
        ["SOTP", f"${sotp.price_per_share:.2f}", _upside(current_price, sotp.price_per_share)],
    ]
    table: str = build_markdown_table(
        ["Method", "Implied Price", "vs. Current"], rows, alignment=["l", "r", "r"]
    )
    return f"## 8. Valuation Summary\n\n**Current Price: ${current_price:.2f}**\n\n{table}\n"


def _section_football_field(
    current_price: float,
    dcf: DCFResult,
    comps: CompsResult,
    sotp: SOTPResult,
) -> str:
    prices: list[float] = [
        dcf.price_per_share_ex_sbc,
        dcf.price_per_share,
        comps.ev_revenue_implied_price,
        comps.ev_ebitda_implied_price,
        comps.p_fcf_implied_price,
        sotp.price_per_share,
    ]
    low: float = min(prices)
    high: float = max(prices)
    mean: float = sum(prices) / len(prices)
    median: float = sorted(prices)[len(prices) // 2]

    rows: list[list[str]] = [
        ["Low", f"${low:.2f}", _upside(current_price, low)],
        ["Mean", f"${mean:.2f}", _upside(current_price, mean)],
        ["Median", f"${median:.2f}", _upside(current_price, median)],
        ["High", f"${high:.2f}", _upside(current_price, high)],
    ]
    table: str = build_markdown_table(
        ["Range", "Price", "vs. Current"], rows, alignment=["l", "r", "r"]
    )
    return f"## 9. Football Field — Implied Price Range\n\n{table}\n"


def _upside(current: float, target: float) -> str:
    pct: float = ((target - current) / current) * 100
    sign: str = "+" if pct >= 0 else ""
    return f"{sign}{pct:.1f}%"
