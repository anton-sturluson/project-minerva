import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";
import { api, errorMessage, type Account } from "./api";
import { TradeScorecard } from "./TradeScorecard";
import { number, percent } from "./format";
import { HitRate } from "./HitRate";
import { type Ledger } from "./records";

type Point = {
  date: string;
  value: string;
  cash: string;
  portfolio: string | null;
  SPY: string;
  QQQ: string;
};
type Report = {
  provisional?: boolean;
  assumptions?: string[];
  modeled_income?: string;
  start: string;
  end: string;
  value: string;
  cash: string;
  return: string | null;
  SPY: string;
  QQQ: string;
  excess_spy: string | null;
  excess_qqq: string | null;
  fetched_at: string;
  source: string;
  warnings: string[];
  series: Point[];
  holdings: {
    ticker: string;
    exchange: string;
    quantity: string;
    close: string;
    value: string;
    weight: string | null;
    basis: string | null;
    unrealized_pnl: string | null;
  }[];
};
const yesterday = () => {
  // Date selection is based on completed US sessions, never an intraday quote.
  const d = new Date(
    new Date().toLocaleDateString("en-CA", { timeZone: "America/New_York" }) +
      "T12:00:00Z",
  );
  d.setUTCDate(d.getUTCDate() - 1);
  return d.toISOString().slice(0, 10);
};

export function Tracker({
  account,
  ledger,
}: {
  account: Account;
  ledger: Ledger;
}) {
  const [start, setStart] = useState(
    ledger.entries[0]?.effective_date ?? yesterday(),
  );
  const [end, setEnd] = useState(yesterday());
  const [report, setReport] = useState<Report | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const generation = useRef(0);
  const compare = useCallback(
    async (from: string, through: string) => {
      const version = ++generation.current;
      setBusy(true);
      setError("");
      setReport(null);
      try {
        const r = await api<Report>(
          `/accounts/${account.id}/performance`,
          {
            method: "POST",
            body: JSON.stringify({ start: from, end: through }),
          },
          60000,
        );
        if (version === generation.current) setReport(r);
      } catch (e) {
        if (version === generation.current) setError(errorMessage(e));
      } finally {
        if (version === generation.current) setBusy(false);
      }
    },
    [account.id],
  );
  useEffect(() => {
    // New records reset the comparison to the full recorded history.
    const from = ledger.entries[0]?.effective_date ?? yesterday();
    const through = yesterday();
    setStart(from);
    setEnd(through);
    setReport(null);
    setError("");
    setBusy(false);
    if (
      ledger.entries.length &&
      from < through &&
      account.base_currency === "USD"
    )
      void compare(from, through);
    return () => {
      generation.current += 1;
    };
  }, [account.base_currency, account.reconstruction, ledger, compare]);
  function submit(e: FormEvent) {
    e.preventDefault();
    void compare(start, end);
  }
  return (
    <section
      id="performance"
      className="tracker"
      aria-labelledby="performance-heading"
    >
      <h2 id="performance-heading">
        {account.reconstruction
          ? "Provisional portfolio vs. the market"
          : "Portfolio vs. the market"}
      </h2>
      <form className="entry-form" onSubmit={submit}>
        <label>
          From
          <input
            aria-label="Performance start"
            type="date"
            required
            value={start}
            min={ledger.entries[0]?.effective_date}
            max={end}
            onChange={(e) => {
              setStart(e.target.value);
              setReport(null);
              setError("");
            }}
            disabled={busy}
          />
        </label>
        <label>
          Through
          <input
            aria-label="Performance end"
            type="date"
            required
            value={end}
            min={start}
            max={yesterday()}
            onChange={(e) => {
              setEnd(e.target.value);
              setReport(null);
              setError("");
            }}
            disabled={busy}
          />
        </label>
        <button
          disabled={
            busy ||
            !ledger.entries.length ||
            start >= end ||
            account.base_currency !== "USD"
          }
          type="submit"
        >
          {busy
            ? "Fetching closes…"
            : error
              ? "Retry comparison"
              : "Compare performance"}
        </button>
      </form>
      {account.base_currency !== "USD" && (
        <p className="form-note">
          Index comparisons currently support USD accounts only.
        </p>
      )}
      {(!ledger.entries.length || start >= end) && (
        <p className="form-note">
          A comparison needs at least two completed market sessions.
        </p>
      )}
      {busy && <p role="status">Loading portfolio and index returns…</p>}
      {error && (
        <p role="alert" className="error">
          {error} Your saved records are unchanged.
        </p>
      )}
      {report && (
        <>
          <p className="report-date">
            {report.start} — {report.end} · {report.source}
          </p>
          {report.warnings.map((w) => (
            <p key={w} role="alert" className="error">
              {w} Portfolio return is withheld.
            </p>
          ))}
          <dl className="scorecard">
            <div>
              <dt>Closing value (USD)</dt>
              <dd>{number(report.value)}</dd>
            </div>
            <div>
              <dt>
                {report.provisional
                  ? "Estimated portfolio return"
                  : "Portfolio return"}
              </dt>
              <dd>{percent(report.return)}</dd>
            </div>
            <div>
              <dt>S&amp;P 500 · SPY</dt>
              <dd>{percent(report.SPY)}</dd>
            </div>
            <div>
              <dt>Nasdaq-100 · QQQ</dt>
              <dd>{percent(report.QQQ)}</dd>
            </div>
          </dl>
          <p>
            Excess return vs. S&amp;P 500 (SPY):{" "}
            {report.excess_spy === null
              ? "—"
              : `${number(String(Number(report.excess_spy) * 100))} pp`}{" "}
            · Nasdaq-100 (QQQ):{" "}
            {report.excess_qqq === null
              ? "—"
              : `${number(String(Number(report.excess_qqq) * 100))} pp`}
          </p>
          <ReturnChart series={report.series} />
          <div
            className="table-scroll"
            tabIndex={0}
            aria-label="Closing valuations"
          >
            <table>
              <thead>
                <tr>
                  <th>Security</th>
                  <th className="number">Shares</th>
                  <th className="number">Close</th>
                  <th className="number">Value (USD)</th>
                  <th className="number">Weight</th>
                  <th className="number">Unrealized P&amp;L</th>
                </tr>
              </thead>
              <tbody>
                {report.holdings.map((h) => (
                  <tr key={`${h.ticker}-${h.exchange}`}>
                    <td>
                      {h.ticker} · {h.exchange}
                    </td>
                    <td className="number">{number(h.quantity, 4)}</td>
                    <td className="number">{number(h.close)}</td>
                    <td className="number">{number(h.value)}</td>
                    <td className="number">{percent(h.weight)}</td>
                    <td className="number">{number(h.unrealized_pnl)}</td>
                  </tr>
                ))}
                <tr>
                  <td>Cash</td>
                  <td>—</td>
                  <td>—</td>
                  <td className="number">{number(report.cash)}</td>
                  <td>—</td>
                  <td>—</td>
                </tr>
              </tbody>
            </table>
          </div>
          <details>
            <summary>Daily values</summary>
            <div
              className="table-scroll"
              tabIndex={0}
              aria-label="Daily performance"
            >
              <table>
                <thead>
                  <tr>
                    <th>Date</th>
                    <th>Value (USD)</th>
                    <th>Portfolio</th>
                    <th>SPY</th>
                    <th>QQQ</th>
                  </tr>
                </thead>
                <tbody>
                  {report.series.map((p) => (
                    <tr key={p.date}>
                      <td>{p.date}</td>
                      <td>{number(p.value)}</td>
                      <td>{percent(p.portfolio)}</td>
                      <td>{percent(p.SPY)}</td>
                      <td>{percent(p.QQQ)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        </>
      )}
      <div id="decisions" className="decisions">
        <TradeScorecard account={account} ledger={ledger} />
        {!account.reconstruction && (
          <HitRate
            key={`${account.id}:${ledger.entries.map((e) => e.id).join(",")}`}
            accountId={account.id}
          />
        )}
      </div>
    </section>
  );
}
function ReturnChart({ series }: { series: Point[] }) {
  const keys = ["portfolio", "SPY", "QQQ"] as const;
  const values = series.flatMap((p) =>
    keys.flatMap((k) => (p[k] === null ? [] : [Number(p[k]) * 100])),
  );
  const low = Math.min(0, ...values),
    high = Math.max(0.01, ...values),
    span = high - low;
  return (
    <figure className="return-chart">
      <figcaption>
        Cumulative return · <span className="portfolio-key">Portfolio</span> /{" "}
        <span className="spy-key">S&amp;P 500 (SPY)</span> /{" "}
        <span className="qqq-key">Nasdaq-100 (QQQ)</span>
      </figcaption>
      <svg
        viewBox="0 0 800 220"
        role="img"
        aria-label="Cumulative portfolio and benchmark returns; exact values in Daily values"
      >
        <text x="0" y="16">
          {high.toFixed(1)}%
        </text>
        <text x="0" y="199">
          {low.toFixed(1)}%
        </text>
        <line
          x1="58"
          x2="795"
          y1={195 - ((0 - low) / span) * 175}
          y2={195 - ((0 - low) / span) * 175}
          stroke="currentColor"
          opacity="0.3"
        />
        {keys.map(
          (k, index) =>
            series.every((p) => p[k] !== null) && (
              <polyline
                key={k}
                className={`${k.toLowerCase()}-line`}
                fill="none"
                strokeWidth="2"
                strokeDasharray={
                  index === 1 ? "7 4" : index === 2 ? "2 4" : undefined
                }
                points={series
                  .map(
                    (p, i) =>
                      `${58 + (i / (series.length - 1)) * 737},${195 - ((Number(p[k]) * 100 - low) / span) * 175}`,
                  )
                  .join(" ")}
              />
            ),
        )}
      </svg>
    </figure>
  );
}
