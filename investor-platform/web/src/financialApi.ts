import { api } from "./api";

export type PerShareMeasure = {
  status: string;
  value?: string | null;
  source_id?: string;
  inputs?: { source_id?: string }[];
};

export type FinancialReport = {
  synthetic: boolean;
  calendar_year: number;
  holdings_date: string;
  api_status: "available" | "partial" | "unavailable";
  market_value_snapshot?: {
    holdings: { issuer_key: string; ticker?: string }[];
  };
  companies: {
    issuer_key: string;
    financial_status?: string;
    profile: {
      review_status?: string;
      issuer?: { name: string };
      facts?: Record<string, PerShareMeasure>;
      calculations?: Record<string, PerShareMeasure>;
      sources: { source_id: string; url: string; published_on: string }[];
    } | null;
  }[];
  weighted_ratios: Record<
    string,
    {
      label: string;
      value: string | null;
      coverage: string | null;
      exclusions: { reason: string }[];
      contributions?: {
        issuer_key: string;
        calculation: {
          inputs: { source_id?: string }[];
          review_note?: string;
        };
      }[];
    }
  >;
};

export const annualFinancials = (year: number) =>
  api<FinancialReport>(`/financials?year=${year}`);
