import { MARKET_DATA_TIMEOUT, api } from "../api";

export type PerShareMeasure = {
  status: "available" | "unavailable";
  value: string | null;
  reason?: string | null;
  method?: string;
  eps_basis?: "basic" | "diluted";
  share_denominator_basis?:
    "basic_weighted_average" | "diluted_weighted_average" | "period_end";
};

export type FinancialComparison = {
  prior_year: number;
  prior_value: string | null;
  status: "calculated" | "not_meaningful" | "unavailable";
  percent_change: string | null;
  reason?: string | null;
  exclusions?: FinancialExclusion[];
  basis_notes?: FinancialBasisNote[];
  coverage?: string | null;
};

export type FinancialExclusion = {
  issuer_key: string;
  ticker: string;
  equity_weight: string | null;
  reason: string;
};

export type FinancialBasisNote = { ticker: string; note: string };

type SummaryMeasure = {
  label: string;
  value: string | null;
  coverage: string | null;
  exclusions: FinancialExclusion[];
  conventions?: { issuer_key: string; ticker: string }[];
  basis_notes?: FinancialBasisNote[];
  comparison?: FinancialComparison;
};

export type FinancialReport = {
  account_id: string;
  synthetic: boolean;
  calendar_year: number;
  holdings_date: string;
  publication_policy?: string;
  api_status: "available" | "partial" | "unavailable";
  market_value_snapshot?: {
    holdings: { issuer_key: string; ticker?: string }[];
  };
  companies: {
    issuer_key: string;
    ticker: string;
    exchange: string;
    name: string;
    equity_weight?: string | null;
    financial_status: "eligible" | "unavailable";
    period?: { start: string; end: string; fiscal_label?: string } | null;
    prior_period?: { start: string; end: string; fiscal_label?: string } | null;
    source_urls?: string[];
    per_share_comparisons?: Record<string, FinancialComparison>;
    per_share_metrics?: Record<string, PerShareMeasure>;
  }[];
  weighted_ratios: Record<string, SummaryMeasure>;
  weighted_company_per_share?: Record<string, SummaryMeasure>;
};

export const annualFinancials = (accountId: string, year: number) =>
  api<FinancialReport>(
    `/accounts/${accountId}/financials?year=${year}`,
    undefined,
    MARKET_DATA_TIMEOUT,
  );
