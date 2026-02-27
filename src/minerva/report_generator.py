"""Report template generator for equity research reports."""

from datetime import date

from minerva.formatting import format_pct, format_usd
from minerva.models import (
    AnalystConsensus,
    BalanceSheetSnapshot,
    CashFlowSnapshot,
    CompanyProfile,
    CompetitorProfile,
    Executive,
    GrowthCatalyst,
    IncomeStatementSnapshot,
    RevenueStream,
    RiskFactor,
)


def _generate_header(profile: CompanyProfile) -> str:
    return f"""# {profile.company_name} ({profile.ticker}) -- Equity Research Report

**Report Date**: {profile.report_date.strftime('%B %d, %Y')}
**Sector**: {profile.sector.value}
**Industry**: {profile.industry}
**Market Cap**: {format_usd(profile.market_cap)}
**Exchange**: {profile.exchange}
**Headquarters**: {profile.headquarters}

---"""


def _generate_executive_summary(profile: CompanyProfile) -> str:
    return f"""## Executive Summary

{profile.reasoning}

---"""


def _generate_revenue_table(streams: list[RevenueStream]) -> str:
    if not streams:
        return "*No revenue stream data available.*"
    header: str = "| Revenue Stream | Revenue | % of Total | YoY Growth | Margin Profile |\n"
    header += "|----------------|---------|------------|------------|----------------|\n"
    rows: list[str] = []
    for s in streams:
        rows.append(
            f"| **{s.name}** | {format_usd(s.revenue_amount)} | {format_pct(s.percentage_of_total)} "
            f"| {format_pct(s.growth_rate_yoy)} | {s.margin_profile or 'N/A'} |"
        )
    return header + "\n".join(rows)


def _generate_executive_table(executives: list[Executive]) -> str:
    if not executives:
        return "*No executive data available.*"
    header: str = "| Name | Title | Background | Founder |\n"
    header += "|------|-------|-----------|--------|\n"
    rows: list[str] = []
    for e in executives:
        founder_flag: str = "Yes" if e.is_founder else "No"
        rows.append(f"| **{e.name}** | {e.title} | {e.background} | {founder_flag} |")
    return header + "\n".join(rows)


def _generate_competitor_table(competitors: list[CompetitorProfile]) -> str:
    if not competitors:
        return "*No competitor data available.*"
    header: str = "| Competitor | Ticker | Market Share | Strengths | Weaknesses vs. Subject |\n"
    header += "|-----------|--------|-------------|-----------|------------------------|\n"
    rows: list[str] = []
    for c in competitors:
        strengths: str = "; ".join(c.strengths) if c.strengths else "N/A"
        weaknesses: str = "; ".join(c.weaknesses_vs_subject) if c.weaknesses_vs_subject else "N/A"
        rows.append(
            f"| **{c.name}** | {c.ticker or 'N/A'} | {format_pct(c.market_share_pct)} "
            f"| {strengths} | {weaknesses} |"
        )
    return header + "\n".join(rows)


def _generate_income_statement_table(statements: list[IncomeStatementSnapshot]) -> str:
    if not statements:
        return "*No income statement data available.*"
    header: str = "| Period | Revenue | Gross Profit | Gross Margin | Op. Income | Op. Margin | Net Income | Adj. EBITDA |\n"
    header += "|--------|---------|-------------|-------------|------------|------------|------------|------------|\n"
    rows: list[str] = []
    for s in statements:
        rows.append(
            f"| {s.period} | {format_usd(s.revenue)} | {format_usd(s.gross_profit)} "
            f"| {format_pct(s.gross_margin_pct)} | {format_usd(s.operating_income)} "
            f"| {format_pct(s.operating_margin_pct)} | {format_usd(s.net_income)} "
            f"| {format_usd(s.adjusted_ebitda)} |"
        )
    return header + "\n".join(rows)


def _generate_balance_sheet_section(bs: BalanceSheetSnapshot | None) -> str:
    if bs is None:
        return "*No balance sheet data available.*"
    return f"""| Metric | Value |
|--------|-------|
| **As of** | {bs.as_of_date} |
| Total Assets | {format_usd(bs.total_assets)} |
| Total Liabilities | {format_usd(bs.total_liabilities)} |
| Shareholders' Equity | {format_usd(bs.shareholders_equity)} |
| Total Debt | {format_usd(bs.total_debt)} |
| Cash & Equivalents | {format_usd(bs.cash_and_equivalents)} |
| Debt/Equity | {format_pct(bs.debt_to_equity_ratio)} |"""


def _generate_cashflow_table(cashflows: list[CashFlowSnapshot]) -> str:
    if not cashflows:
        return "*No cash flow data available.*"
    header: str = "| Period | Op. Cash Flow | CapEx | Free Cash Flow | Share Repurchases |\n"
    header += "|--------|--------------|-------|----------------|-------------------|\n"
    rows: list[str] = []
    for cf in cashflows:
        rows.append(
            f"| {cf.period} | {format_usd(cf.operating_cash_flow)} | {format_usd(cf.capital_expenditures)} "
            f"| {format_usd(cf.free_cash_flow)} | {format_usd(cf.share_repurchases)} |"
        )
    return header + "\n".join(rows)


def _generate_risk_section(risks: list[RiskFactor]) -> str:
    if not risks:
        return "*No risk factors identified.*"
    lines: list[str] = []
    for i, r in enumerate(risks, 1):
        mitigants: str = ""
        if r.mitigating_factors:
            mitigants = "\n" + "\n".join(f"  - {m}" for m in r.mitigating_factors)
        lines.append(f"**{i}. {r.name} ({r.severity.value})**\n{r.description}{mitigants}\n")
    return "\n".join(lines)


def _generate_catalyst_section(catalysts: list[GrowthCatalyst]) -> str:
    if not catalysts:
        return "*No growth catalysts identified.*"
    lines: list[str] = []
    for c in catalysts:
        lines.append(f"- **{c.name}** [{c.timeframe}] ({c.potential_impact} impact): {c.description}")
    return "\n".join(lines)


def _generate_analyst_section(consensus: AnalystConsensus | None) -> str:
    if consensus is None:
        return "*No analyst consensus data available.*"
    return f"""| Metric | Value |
|--------|-------|
| Total Analysts | {consensus.total_analysts} |
| Buy | {consensus.buy_count} |
| Hold | {consensus.hold_count} |
| Sell | {consensus.sell_count} |
| Consensus Rating | **{consensus.consensus_rating.value}** |
| Avg. Price Target | {format_usd(consensus.average_price_target, auto_scale=False)} |
| High Target | {format_usd(consensus.high_price_target, auto_scale=False)} |
| Low Target | {format_usd(consensus.low_price_target, auto_scale=False)} |
| Current Price | {format_usd(consensus.current_price, auto_scale=False)} |
| Implied Upside | {format_pct(consensus.implied_upside_pct)} |

{consensus.reasoning}"""


def generate_report(profile: CompanyProfile) -> str:
    """Generate a complete equity research report in markdown from a CompanyProfile."""
    sections: list[str] = [
        _generate_header(profile),
        "",
        _generate_executive_summary(profile),
        "",
        "## 1. Company Overview",
        f"\n{profile.business_description}\n",
        f"### History & Milestones\n\n{profile.history_and_milestones}\n",
        "",
        "## 2. Business Model & Revenue Analysis",
        f"\n### Revenue Streams\n\n{_generate_revenue_table(profile.revenue_streams)}\n",
        f"\n### TAM\n\n{profile.total_addressable_market or 'N/A'}\n",
        "",
        "## 3. Industry & Competitive Landscape",
        f"\n{_generate_competitor_table(profile.competitors)}\n",
        f"\n### Competitive Moats\n",
        "\n".join(f"- {moat}" for moat in profile.competitive_moats) if profile.competitive_moats else "N/A",
        "",
        "## 4. Leadership & Governance",
        f"\n{_generate_executive_table(profile.executives)}\n",
        f"\nInsider Ownership: {format_pct(profile.insider_ownership_pct)}",
        f"Institutional Ownership: {format_pct(profile.institutional_ownership_pct)}\n",
        "",
        "## 5. Financial Analysis",
        f"\n### Income Statement\n\n{_generate_income_statement_table(profile.income_statements)}\n",
        f"\n### Balance Sheet\n\n{_generate_balance_sheet_section(profile.balance_sheet)}\n",
        f"\n### Cash Flow\n\n{_generate_cashflow_table(profile.cash_flows)}\n",
        "",
        "## 6. Growth Catalysts",
        f"\n{_generate_catalyst_section(profile.growth_catalysts)}\n",
        "",
        "## 7. Risk Assessment",
        f"\n{_generate_risk_section(profile.risk_factors)}\n",
        "",
        "## 8. Analyst Sentiment & Consensus",
        f"\n{_generate_analyst_section(profile.analyst_consensus)}\n",
        "",
        "## 9. Conclusion",
        f"\n### Bull Case\n\n{profile.bull_case or 'N/A'}\n",
        f"\n### Bear Case\n\n{profile.bear_case or 'N/A'}\n",
        "\n### Key Metrics to Watch\n",
        "\n".join(f"- {m}" for m in profile.key_metrics_to_watch) if profile.key_metrics_to_watch else "N/A",
        "",
        "---",
        f"\n*Report generated on {profile.report_date.strftime('%B %d, %Y')}*",
    ]
    return "\n".join(sections)
