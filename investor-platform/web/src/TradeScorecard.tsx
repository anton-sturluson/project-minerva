import { useEffect, useState } from "react";
import { api, errorMessage, type Account } from "./api";
import { number, percent } from "./format";
import { type Ledger } from "./records";

type Stats = {
  closed: number;
  open: number;
  unknown: number;
  wins: number;
  losses: number;
  breakeven: number;
  win_rate: string | null;
  average_win: string | null;
  average_loss: string | null;
  payoff_ratio: string | null;
  simulated_positions?: number;
  quote_start?: string | null;
  quote_end?: string | null;
  episodes: {
    ticker: string;
    exchange: string;
    closed_on: string;
    pnl: string | null;
    hypothetical?: boolean;
  }[];
};
export function TradeScorecard({
  account,
  ledger,
}: {
  account: Account;
  ledger: Ledger;
}) {
  const [hypothetical, setHypothetical] = useState(false);
  const [stats, setStats] = useState<Stats | null>(null);
  const [statsError, setStatsError] = useState("");
  const [retryStats, setRetryStats] = useState(0);
  useEffect(() => {
    let active = true;
    setStats(null);
    setStatsError("");
    void api<Stats>(
      `/accounts/${account.id}/statistics${hypothetical ? "/hypothetical" : ""}`,
    )
      .then((s) => {
        if (active) setStats(s);
      })
      .catch((e) => {
        if (active) setStatsError(errorMessage(e));
      });
    return () => {
      active = false;
    };
  }, [account.id, ledger, retryStats, hypothetical]);
  return (
    <>
      <h3>
        Trade scorecard <small>· all recorded history</small>
      </h3>
      <label className="form-note scorecard-toggle">
        <input
          type="checkbox"
          checked={hypothetical}
          onChange={(event) => setHypothetical(event.target.checked)}
        />{" "}
        Hypothetical: close all open positions
      </label>
      {hypothetical && stats && (
        <p className="form-note">
          {stats.simulated_positions ? (
            <>
              Latest closes · {stats.quote_start}
              {stats.quote_start !== stats.quote_end
                ? ` — ${stats.quote_end}`
                : ""}{" "}
              · before selling fees and taxes.
            </>
          ) : (
            "No open positions to close."
          )}
        </p>
      )}
      {statsError && (
        <p role="alert" className="error">
          {statsError}{" "}
          <button onClick={() => setRetryStats((n) => n + 1)}>
            Retry scorecard
          </button>
        </p>
      )}
      {!stats && !statsError && <p>Loading trade scorecard…</p>}
      {stats && (
        <>
          <dl className="scorecard">
            <div>
              <dt>Win rate</dt>
              <dd data-testid="win-rate">{percent(stats.win_rate)}</dd>
            </div>
            <div>
              <dt>Payoff ratio</dt>
              <dd data-testid="payoff-ratio">
                {stats.payoff_ratio === null
                  ? "—"
                  : `${number(stats.payoff_ratio)}×`}
              </dd>
            </div>
            <div>
              <dt>Average win ({account.base_currency})</dt>
              <dd>{number(stats.average_win)}</dd>
            </div>
            <div>
              <dt>Average loss ({account.base_currency})</dt>
              <dd>{number(stats.average_loss)}</dd>
            </div>
          </dl>
          <p className="form-note">
            {stats.wins} wins · {stats.losses} losses · {stats.breakeven}{" "}
            breakeven. Excluded: {stats.unknown} unknown basis · {stats.open}{" "}
            open positions.
          </p>
          <details>
            <summary>
              {hypothetical
                ? "Closed + hypothetical positions"
                : "Closed positions"}
            </summary>
            {stats.episodes.length > 0 && (
              <div
                className="table-scroll"
                tabIndex={0}
                aria-label="Closed positions"
              >
                <table>
                  <thead>
                    <tr>
                      <th>Security</th>
                      <th>Closed</th>
                      <th className="number">
                        P&amp;L ({account.base_currency})
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {stats.episodes.map((s, i) => (
                      <tr key={i}>
                        <td>
                          {s.ticker} ·{" "}
                          {s.exchange === "UNVERIFIED"
                            ? "Exchange unconfirmed"
                            : s.exchange}
                        </td>
                        <td>{s.hypothetical ? "Hypothetical" : s.closed_on}</td>
                        <td className="number">
                          {s.pnl === null ? "Unknown basis" : number(s.pnl)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </details>
        </>
      )}
    </>
  );
}
