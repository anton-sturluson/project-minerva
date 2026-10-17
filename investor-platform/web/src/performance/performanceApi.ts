import { api, MARKET_DATA_TIMEOUT } from "../api";

export type PerformanceScope = "stocks" | "account";
export type BenchmarkMode = "buy_hold" | "matched" | "funded_hold";

export type PerformanceBaseline = "history" | "recorded";

export type PerformancePoint = {
  date: string;
  value: string;
  cash: string;
  portfolio: string | null;
  SPY: string;
  QQQ: string;
};
type CAGR = {
  portfolio: string | null;
  SPY: string | null;
  QQQ: string | null;
};
export type PerformanceReport = {
  cash_method?: "purchase_shortfall" | "recorded";
  dividend_policy?: "unrecorded_zero";
  benchmark_values?: Record<"SPY" | "QQQ", { value: string }>;
  funding_estimate?: { capital: string; estimated_dividends: string };
  benchmark_mode?: BenchmarkMode;
  matched_benchmarks?: Record<
    "SPY" | "QQQ",
    {
      value: string;
    }
  > | null;
  scope?: PerformanceScope;
  baseline?: PerformanceBaseline;
  security_ids?: string[];
  cagr: CAGR;
  scenario?:
    | (PerformanceReport & {
        excluded: { id: string; ticker: string; exchange: string }[];
      })
    | null;
  scenario_error?: string | null;
  provisional?: boolean;
  start: string;
  end: string;
  value: string;
  cash: string;
  receivables?: string;
  return: string | null;
  SPY: string;
  QQQ: string;
  excess_spy: string | null;
  excess_qqq: string | null;
  fetched_at: string;
  source: string;
  warnings: string[];
  series: PerformancePoint[];
};

export type PerformanceRequest = {
  start: string;
  end: string;
  exclude_security_ids: string[];
  baseline: PerformanceBaseline;
  scope: PerformanceScope;
  anchor_date?: string;
  benchmark_mode: BenchmarkMode;
};

export function fetchPerformance(
  accountId: string,
  request: PerformanceRequest,
) {
  return api<PerformanceReport>(
    `/accounts/${accountId}/performance`,
    {
      method: "POST",
      body: JSON.stringify({
        ...request,
        baseline:
          request.baseline === "recorded" ? request.baseline : undefined,
        exclude_security_ids: request.exclude_security_ids.length
          ? request.exclude_security_ids
          : undefined,
      }),
    },
    MARKET_DATA_TIMEOUT,
  );
}
