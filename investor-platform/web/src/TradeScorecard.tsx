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
  episodes: {
    ticker: string;
    exchange: string;
    closed_on: string;
    pnl: string | null;
  }[];
};
export function TradeScorecard({
  account,
  ledger,
}: {
  account: Account;
  ledger: Ledger;
}) {
  const [stats, setStats] = useState<Stats | null>(null);
  const [statsError, setStatsError] = useState("");
  const [retryStats, setRetryStats] = useState(0);
  useEffect(() => {
    let active = true;
    setStats(null);
    setStatsError("");
    void api<Stats>(`/accounts/${account.id}/statistics`)
      .then((s) => {
        if (active) setStats(s);
      })
      .catch((e) => {
        if (active) setStatsError(errorMessage(e));
      });
    return () => {
      active = false;
    };
  }, [account.id, ledger, retryStats]);
  return (
    <>
      <h3>
        Trade scorecard <small>· all recorded history</small>
      </h3>
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
            <summary>Closed positions</summary>
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
                          {s.ticker} · {s.exchange}
                        </td>
                        <td>{s.closed_on}</td>
                        <td className="number">{number(s.pnl)}</td>
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
