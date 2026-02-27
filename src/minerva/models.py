"""Pydantic data models for equity research analysis."""

from datetime import date
from enum import Enum
from pydantic import BaseModel, Field


class Sector(str, Enum):
    TECHNOLOGY = "Technology"
    HEALTHCARE = "Healthcare"
    FINANCIALS = "Financials"
    CONSUMER_DISCRETIONARY = "Consumer Discretionary"
    CONSUMER_STAPLES = "Consumer Staples"
    INDUSTRIALS = "Industrials"
    ENERGY = "Energy"
    MATERIALS = "Materials"
    UTILITIES = "Utilities"
    REAL_ESTATE = "Real Estate"
    COMMUNICATION_SERVICES = "Communication Services"


class RiskSeverity(str, Enum):
    LOW = "Low"
    MEDIUM = "Medium"
    MEDIUM_HIGH = "Medium-High"
    HIGH = "High"
    CRITICAL = "Critical"


class AnalystRating(str, Enum):
    STRONG_BUY = "Strong Buy"
    BUY = "Buy"
    MODERATE_BUY = "Moderate Buy"
    HOLD = "Hold"
    SELL = "Sell"
    STRONG_SELL = "Strong Sell"


class RevenueStream(BaseModel):
    """Single revenue stream within a company's business model."""
    reasoning: str = Field(description="Why this revenue stream matters to the investment thesis")
    name: str
    description: str
    revenue_amount: float | None = Field(default=None, description="Annual revenue in USD")
    percentage_of_total: float | None = Field(default=None, description="Percentage of total revenue (0-100)")
    growth_rate_yoy: float | None = Field(default=None, description="Year-over-year growth rate (0-100)")
    margin_profile: str | None = Field(default=None, description="Qualitative margin description (e.g. 'High', 'Low')")
    gross_margin: float | None = Field(default=None, description="Gross margin percentage (0-100)")


class GeographicSegment(BaseModel):
    """Geographic revenue or presence segment."""
    reasoning: str = Field(description="Significance of this geography to the thesis")
    name: str
    status: str = Field(description="e.g. 'Core market', 'Launched 2024', 'Planned'")
    revenue_percentage: float | None = Field(default=None, description="Percentage of total revenue (0-100)")
    notes: str | None = None


class Executive(BaseModel):
    """Company executive or board member profile."""
    reasoning: str = Field(description="Why this person's background matters")
    name: str
    title: str
    background: str
    tenure_years: float | None = None
    is_founder: bool = False
    total_compensation: float | None = Field(default=None, description="Total annual compensation in USD")


class RiskFactor(BaseModel):
    """Individual risk factor for an investment."""
    reasoning: str = Field(description="Analysis of why this risk matters and its probability")
    name: str
    description: str
    severity: RiskSeverity
    category: str = Field(description="e.g. 'Cyclical', 'Competitive', 'Regulatory', 'Operational'")
    mitigating_factors: list[str] = Field(default_factory=list)


class GrowthCatalyst(BaseModel):
    """Growth catalyst or driver for future value creation."""
    reasoning: str = Field(description="Analysis of the catalyst's potential impact and timeline")
    name: str
    description: str
    timeframe: str = Field(description="e.g. 'Near-term (0-12 months)', 'Long-term (2-5 years)'")
    potential_impact: str = Field(description="e.g. 'High', 'Medium', 'Incremental'")


class IncomeStatementSnapshot(BaseModel):
    """Annual or quarterly income statement summary."""
    period: str = Field(description="e.g. 'FY2024', 'Q3 2025'")
    revenue: float = Field(description="Total revenue in USD")
    cost_of_revenue: float | None = None
    gross_profit: float | None = None
    gross_margin_pct: float | None = Field(default=None, description="Gross margin percentage (0-100)")
    operating_income: float | None = None
    operating_margin_pct: float | None = None
    net_income: float | None = None
    adjusted_ebitda: float | None = None
    stock_based_compensation: float | None = None


class BalanceSheetSnapshot(BaseModel):
    """Balance sheet summary at a point in time."""
    as_of_date: str = Field(description="e.g. 'FY2024', 'Q3 2025'")
    total_assets: float
    total_liabilities: float
    shareholders_equity: float
    total_debt: float
    cash_and_equivalents: float
    debt_to_equity_ratio: float | None = None


class CashFlowSnapshot(BaseModel):
    """Cash flow summary for a period."""
    period: str
    operating_cash_flow: float
    capital_expenditures: float | None = None
    free_cash_flow: float | None = None
    share_repurchases: float | None = None


class AnalystConsensus(BaseModel):
    """Analyst consensus ratings and price targets."""
    reasoning: str = Field(description="Interpretation of what analyst sentiment implies")
    total_analysts: int
    buy_count: int
    hold_count: int
    sell_count: int
    consensus_rating: AnalystRating
    average_price_target: float
    high_price_target: float
    low_price_target: float
    current_price: float
    implied_upside_pct: float | None = None


class CompetitorProfile(BaseModel):
    """Brief competitor profile for competitive landscape analysis."""
    reasoning: str = Field(description="How this competitor affects the investment thesis")
    name: str
    ticker: str | None = None
    market_share_pct: float | None = None
    strengths: list[str] = Field(default_factory=list)
    weaknesses_vs_subject: list[str] = Field(default_factory=list)


class CompanyProfile(BaseModel):
    """Top-level company profile aggregating all research dimensions."""
    reasoning: str = Field(description="High-level investment thesis summary")
    ticker: str
    company_name: str
    report_date: date
    sector: Sector
    industry: str
    market_cap: float = Field(description="Market cap in USD")
    exchange: str
    headquarters: str

    business_description: str
    history_and_milestones: str

    revenue_streams: list[RevenueStream] = Field(default_factory=list)
    geographic_segments: list[GeographicSegment] = Field(default_factory=list)
    total_addressable_market: str | None = None

    executives: list[Executive] = Field(default_factory=list)
    insider_ownership_pct: float | None = None
    institutional_ownership_pct: float | None = None

    income_statements: list[IncomeStatementSnapshot] = Field(default_factory=list)
    balance_sheet: BalanceSheetSnapshot | None = None
    cash_flows: list[CashFlowSnapshot] = Field(default_factory=list)

    competitors: list[CompetitorProfile] = Field(default_factory=list)
    competitive_moats: list[str] = Field(default_factory=list)

    growth_catalysts: list[GrowthCatalyst] = Field(default_factory=list)
    risk_factors: list[RiskFactor] = Field(default_factory=list)
    analyst_consensus: AnalystConsensus | None = None

    key_metrics_to_watch: list[str] = Field(default_factory=list)
    bull_case: str | None = None
    bear_case: str | None = None
