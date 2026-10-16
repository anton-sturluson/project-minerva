import { api } from "./api";

export type PerShareMeasure = {
  status: "available" | "unavailable";
  value: string | null;
  reason?: string | null;
  method?: string;
  eps_basis?: "basic" | "diluted";
  share_denominator_basis?:
    "basic_weighted_average" | "diluted_weighted_average" | "period_end";
};

export type PerShareComparison = {
  prior_year: number;
  prior_value: string | null;
  status: "calculated" | "not_meaningful" | "unavailable";
  percent_change: string | null;
  reason?: string | null;
  exclusions?: FinancialExclusion[];
};

type FinancialExclusion = {
  issuer_key?: string;
  ticker?: string;
  equity_weight?: string | null;
  reason: string;
};

type SummaryMeasure = {
  label: string;
  value: string | null;
  coverage: string | null;
  exclusions: FinancialExclusion[];
  conventions?: { issuer_key: string; ticker: string }[];
  comparison?: PerShareComparison;
};

export type FinancialReport = {
  account_id: string;
  synthetic: boolean;
  calendar_year: number;
  holdings_date: string;
  api_status: "available" | "partial" | "unavailable";
  market_value_snapshot?: {
    holdings: { issuer_key: string; ticker?: string }[];
  };
  companies: {
    issuer_key: string;
    ticker: string;
    name: string;
    equity_weight?: string | null;
    financial_status: "eligible" | "unavailable";
    per_share_comparisons?: Record<string, PerShareComparison>;
    per_share_metrics?: Record<string, PerShareMeasure>;
  }[];
  weighted_ratios: Record<string, SummaryMeasure>;
  weighted_company_per_share?: Record<string, SummaryMeasure>;
};

export const annualFinancials = (accountId: string, year: number) =>
  api<FinancialReport>(`/accounts/${accountId}/financials?year=${year}`);
