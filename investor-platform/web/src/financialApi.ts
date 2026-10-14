import { api } from "./api";

export type FinancialReport = {
  synthetic: boolean;
  calendar_year: number;
  holdings_date: string;
  api_status: "available" | "partial" | "unavailable";
  companies: {
    issuer_key: string;
    profile: {
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
