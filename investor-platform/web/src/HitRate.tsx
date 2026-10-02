import { useState } from "react";
import { api, errorMessage } from "./api";
import { number, percent } from "./format";

type Benchmark = "SPY" | "QQQ";
type Result = {
  benchmarks: Record<
    Benchmark,
    { hit_rate: string | null; hits: number; evaluated: number; ties: number }
  >;
  open: number;
  excluded: number;
  source: string;
  fetched_at: string;
  episodes: {
    ticker: string;
    exchange: string;
    opened_on: string;
    closed_on: string;
    excluded: string | null;
    pnl?: string;
    benchmarks?: Record<Benchmark, { pnl: string; excess: string }>;
  }[];
};
export function HitRate({ accountId }: { accountId: string }) {
  const [result, setResult] = useState<Result | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function calculate() {
    setBusy(true);
    setError("");
    setResult(null);
    try {
      setResult(
        await api<Result>(
          `/accounts/${accountId}/hit-rate`,
          { method: "POST" },
          60000,
        ),
      );
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <section aria-label="Benchmark hit rate">
      <dl className="scorecard">
        {(["SPY", "QQQ"] as const).map((benchmark) => {
          const metric = result?.benchmarks[benchmark];
          return (
            <div key={benchmark}>
              <dt>Hit rate · {benchmark}</dt>
              <dd data-testid={`hit-rate-${benchmark}`}>
                {percent(metric?.hit_rate ?? null)}
              </dd>
              {metric && (
                <span className="form-note">
                  {metric.hits} / {metric.evaluated} beat the market ·{" "}
                  {metric.ties} tied
                </span>
              )}
            </div>
          );
        })}
      </dl>
      <p className="form-note">
        Hit rate = closed investment decisions that beat the market / evaluated
        decisions. SPY tracks the S&amp;P 500; QQQ tracks the Nasdaq-100. A
        profitable trade can still miss the benchmark.
      </p>
      <button disabled={busy} onClick={() => void calculate()}>
        {busy ? "Calculating hit rate…" : "Calculate hit rate"}
      </button>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {result && (
        <>
          <p className="form-note">
            {result.excluded} closed decisions excluded · {result.open} open
            positions excluded. All recorded history; independent of any chart
            dates.
          </p>
          {result.benchmarks.SPY.evaluated === 0 && (
            <p>
              No eligible closed decisions. Hit rate is unavailable, not zero.
            </p>
          )}
          <p className="report-date">
            {result.source} · fetched{" "}
            {new Date(result.fetched_at).toLocaleString()}
          </p>
        </>
      )}
      <details>
        <summary>Hit rate method &amp; decision results</summary>
        <p className="form-note">
          Each decision runs from no shares to no shares. Benchmark investments
          match each purchase’s cost (including fees), with FIFO portions
          exiting on your sale dates. Compare your net dollar P&amp;L with the
          matched benchmark gain using daily total-return closes. Ties after
          rounding excess dollars to cents count in the denominator, but are not
          hits. This is a closing-price approximation, not intraday execution
          matching.
        </p>
        <p className="form-note">
          Opening positions lack original purchase dates. Positions with
          distributions, splits, incomplete prices or unsupported listings are
          excluded; income is not yet linked to individual stocks. Only
          completed sessions in the past ten years are supported. Provider data
          is single-source and may be revised. Payoff ratio remains average
          profitable dollar gain / average absolute dollar loss; its winners are
          defined by profit, not market outperformance.
        </p>
        {result && result.episodes.length > 0 && (
          <div
            className="table-scroll"
            tabIndex={0}
            aria-label="Hit rate decisions"
          >
            <table>
              <thead>
                <tr>
                  <th>Decision</th>
                  <th>Period</th>
                  <th>P&amp;L (USD)</th>
                  <th>SPY excess (USD)</th>
                  <th>QQQ excess (USD)</th>
                  <th>Excluded because</th>
                </tr>
              </thead>
              <tbody>
                {result.episodes.map((row, i) => (
                  <tr key={i}>
                    <td>
                      {row.ticker} · {row.exchange}
                    </td>
                    <td>
                      {row.opened_on} — {row.closed_on}
                    </td>
                    <td>{row.pnl === undefined ? "—" : number(row.pnl)}</td>
                    <td>
                      {row.benchmarks ? number(row.benchmarks.SPY.excess) : "—"}
                    </td>
                    <td>
                      {row.benchmarks ? number(row.benchmarks.QQQ.excess) : "—"}
                    </td>
                    <td>{row.excluded ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </details>
    </section>
  );
}
