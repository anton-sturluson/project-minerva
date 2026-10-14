import { api } from "./api";

export type FinancialSource = {
  source_id: string;
  url: string;
  published_on: string;
};
export type FinancialMeasure = {
  status: string;
  value?: string | null;
  reason?: string | null;
  source_id?: string;
  inputs?: { source_id?: string }[];
  share_basis?: {
    classes: string[];
    split_adjusted_through: string;
    equivalence_note?: string;
  };
};
export type FinancialProfile = {
  issuer: { name: string };
  period: { start: string; end: string; fiscal_label: string };
  sources: FinancialSource[];
  facts: Record<string, FinancialMeasure>;
  calculations: Record<string, FinancialMeasure>;
};
export type FinancialCompany = {
  issuer_key: string;
  equity_weight: string | null;
  profile: FinancialProfile | null;
  financial_status: string;
  reason: string | null;
};
export type FinancialReport = {
  synthetic: boolean;
  calendar_year: number;
  holdings_date: string;
  api_status: "available" | "partial" | "unavailable";
  companies: FinancialCompany[];
  market_value_snapshot: {
    holdings: { issuer_key: string; ticker?: string }[];
  };
  weighted_ratios: Record<
    string,
    FinancialMeasure & {
      label: string;
      coverage: string | null;
      exclusions: { issuer_key: string; reason: string }[];
    }
  >;
};

export const annualFinancials = (year: number) =>
  api<FinancialReport>(`/financials?year=${year}`);
