import { useCallback, useEffect, useRef, useState } from "react";
import { MARKET_DATA_TIMEOUT, api, errorMessage } from "../api";
import { number, percent } from "../format";

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
export function HitRate({
  accountId,
  visible,
  marketRevision,
}: {
  accountId: string;
  visible: boolean;
  marketRevision: number;
}) {
  const [result, setResult] = useState<Result | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const requested = useRef(false);
  const activeRequest = useRef<AbortController | null>(null);
  const calculate = useCallback(async () => {
    requested.current = true;
    activeRequest.current?.abort();
    const controller = new AbortController();
    activeRequest.current = controller;
    setBusy(true);
    setError("");
    setResult(null);
    try {
      const next = await api<Result>(
        `/accounts/${accountId}/hit-rate`,
        { method: "POST", signal: controller.signal },
        MARKET_DATA_TIMEOUT,
      );
      if (!controller.signal.aborted) setResult(next);
    } catch (e) {
      if (!controller.signal.aborted) setError(errorMessage(e));
    } finally {
      if (!controller.signal.aborted) setBusy(false);
    }
  }, [accountId]);
  useEffect(() => {
    if (!visible) return;
    if (requested.current) void calculate();
    return () => activeRequest.current?.abort();
  }, [calculate, marketRevision, visible]);
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
        Hit rate: closed decisions that beat each index.
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
            positions excluded · all recorded history.
          </p>
          {result.benchmarks.SPY.evaluated === 0 && (
            <p>
              No eligible closed decisions. Hit rate is unavailable, not zero.
            </p>
          )}
          <p className="report-date">
            {result.source} · calculated{" "}
            {new Date(result.fetched_at).toLocaleString()}
          </p>
        </>
      )}
      <details>
        <summary>Decision results</summary>
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
