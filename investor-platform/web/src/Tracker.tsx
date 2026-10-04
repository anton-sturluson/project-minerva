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
import { Holdings } from "./Holdings";
import { type Ledger } from "./records";

type Baseline = "history" | "recorded";

type Point = {
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
export type Report = {
  baseline?: Baseline;
  security_ids?: string[];
  cagr: CAGR;
  scenario?:
    | (Report & {
        excluded: { id: string; ticker: string; exchange: string }[];
      })
    | null;
  scenario_error?: string | null;
  provisional?: boolean;
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

const recentStart = (ledger: Ledger, through: string) => {
  const date = new Date(through + "T12:00:00Z");
  date.setUTCDate(date.getUTCDate() - 90);
  const recent = date.toISOString().slice(0, 10);
  const first = ledger.entries[0]?.effective_date ?? through;
  return first > recent ? first : recent;
};

export function Tracker({
  account,
  ledger,
}: {
  account: Account;
  ledger: Ledger;
}) {
  const [baseline, setBaseline] = useState<Baseline>(
    account.reconstruction ? "recorded" : "history",
  );
  const [start, setStart] = useState(
    account.reconstruction
      ? recentStart(ledger, yesterday())
      : (ledger.entries[0]?.effective_date ?? yesterday()),
  );
  const [end, setEnd] = useState(yesterday());
  const [excluded, setExcluded] = useState<string[]>([]);
  const securities = [
    ...new Map(
      ledger.entries
        .filter((e) => e.security && e.effective_date <= end)
        .map((e) => [e.security!.id, e.security!]),
    ).values(),
  ];
  const [report, setReport] = useState<Report | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const generation = useRef(0);
  const compare = useCallback(
    async (
      from: string,
      through: string,
      exclusions: string[] = [],
      basis: Baseline = "history",
    ) => {
      const version = ++generation.current;
      setBusy(true);
      setError("");
      setReport((current) =>
        current ? { ...current, scenario: null, scenario_error: null } : null,
      );
      try {
        const r = await api<Report>(
          `/accounts/${account.id}/performance`,
          {
            method: "POST",
            body: JSON.stringify({
              start: from,
              end: through,
              ...(basis === "recorded" ? { baseline: basis } : {}),
              ...(exclusions.length
                ? { exclude_security_ids: exclusions }
                : {}),
            }),
          },
          60000,
        );
        if (version === generation.current) setReport(r);
      } catch (e) {
        if (version === generation.current) {
          setReport(null);
          setError(errorMessage(e));
        }
      } finally {
        if (version === generation.current) setBusy(false);
      }
    },
    [account.id],
  );
  useEffect(() => {
    // Incomplete imports start with a recent, explicitly recorded-balance estimate.
    const through = yesterday();
    const basis = account.reconstruction ? "recorded" : "history";
    const from = account.reconstruction
      ? recentStart(ledger, through)
      : (ledger.entries[0]?.effective_date ?? through);
    setBaseline(basis);
    setExcluded([]);
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
      void compare(from, through, [], basis);
    return () => {
      generation.current += 1;
    };
  }, [account.base_currency, account.reconstruction, ledger, compare]);
  function submit(e: FormEvent) {
    e.preventDefault();
    void compare(start, end, excluded, baseline);
  }
  function choosePeriod(basis: Baseline) {
    const through = yesterday();
    const from =
      basis === "recorded"
        ? recentStart(ledger, through)
        : (ledger.entries[0]?.effective_date ?? through);
    setBaseline(basis);
    setStart(from);
    setEnd(through);
    setExcluded([]);
    setReport(null);
    void compare(from, through, [], basis);
  }
  return (
    <>
      <div id="decisions" className="decisions">
        <TradeScorecard account={account} ledger={ledger} />
        {!account.reconstruction && (
          <HitRate
            key={`${account.id}:${ledger.entries.map((e) => e.id).join(",")}`}
            accountId={account.id}
          />
        )}
      </div>

      <Holdings ledger={ledger} accountId={account.id} />
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
        <p className="period-shortcuts">
          <button
            type="button"
            disabled={
              busy || !ledger.entries.length || account.base_currency !== "USD"
            }
            onClick={() => choosePeriod("recorded")}
          >
            Last 90 days
          </button>{" "}
          <button
            type="button"
            disabled={
              busy || !ledger.entries.length || account.base_currency !== "USD"
            }
            onClick={() => choosePeriod("history")}
          >
            Full history
          </button>
        </p>
        {baseline === "recorded" && (
          <p className="form-note">
            Uses recorded starting cash and shares; earlier income is not
            reconstructed.
          </p>
        )}
        <form className="entry-form performance-controls" onSubmit={submit}>
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
                setExcluded([]);
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
                setExcluded([]);
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
          {securities.length > 0 && (
            <details className="scenario-picker">
              <summary>
                Exclude stocks{excluded.length ? ` (${excluded.length})` : ""}
              </summary>
              <fieldset disabled={busy}>
                <legend>
                  {baseline === "recorded"
                    ? "Exclude from this period"
                    : "What if I never held these stocks?"}
                </legend>
                {securities
                  .filter(
                    (security) =>
                      baseline !== "recorded" ||
                      !report?.security_ids ||
                      report.security_ids.includes(security.id),
                  )
                  .map((security) => (
                    <label key={security.id}>
                      <input
                        type="checkbox"
                        checked={excluded.includes(security.id)}
                        onChange={(e) => {
                          setExcluded((current) =>
                            e.target.checked
                              ? [...current, security.id]
                              : current.filter((id) => id !== security.id),
                          );
                          setReport((current) =>
                            current
                              ? {
                                  ...current,
                                  scenario: null,
                                  scenario_error: null,
                                }
                              : null,
                          );
                          setError("");
                        }}
                      />
                      {security.ticker} · {security.exchange}
                    </label>
                  ))}
                <button
                  type="button"
                  onClick={() => {
                    setExcluded([]);
                    setReport((current) =>
                      current
                        ? { ...current, scenario: null, scenario_error: null }
                        : null,
                    );
                    setError("");
                  }}
                >
                  Clear exclusions
                </button>
              </fieldset>
            </details>
          )}
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
            {error}
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
            <p>
              <span>Closing value (USD)</span>{" "}
              <strong>{number(report.value)}</strong>
            </p>
            {report.scenario_error && (
              <p role="alert" className="error">
                {report.scenario_error}. Original performance is shown.
              </p>
            )}
            {report.scenario && (
              <p className="form-note">
                Without{" "}
                {report.scenario.excluded
                  .map((s) => `${s.ticker} · ${s.exchange}`)
                  .join(", ")}{" "}
                · unused cash retained
              </p>
            )}
            <div
              className="table-scroll"
              tabIndex={0}
              aria-label="Performance summary"
            >
              <table>
                <thead>
                  <tr>
                    <th>Return</th>
                    <th className="number">Cumulative</th>
                    <th className="number">CAGR</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td>
                      {report.provisional
                        ? "Estimated portfolio return"
                        : "Portfolio return"}
                    </td>
                    <td className="number">{percent(report.return)}</td>
                    <td className="number">
                      {percent(report.cagr?.portfolio ?? null)}
                    </td>
                  </tr>
                  {report.scenario && (
                    <tr>
                      <td>Without excluded stocks</td>
                      <td className="number">
                        {percent(report.scenario.return)}
                      </td>
                      <td className="number">
                        {percent(report.scenario.cagr.portfolio)}
                      </td>
                    </tr>
                  )}
                  <tr>
                    <td>S&amp;P 500 · SPY</td>
                    <td className="number">{percent(report.SPY)}</td>
                    <td className="number">
                      {percent(report.cagr?.SPY ?? null)}
                    </td>
                  </tr>
                  <tr>
                    <td>Nasdaq-100 · QQQ</td>
                    <td className="number">{percent(report.QQQ)}</td>
                    <td className="number">
                      {percent(report.cagr?.QQQ ?? null)}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
            {(Date.parse(report.end) - Date.parse(report.start)) / 86400000 <
              365 && <p className="form-note">CAGR needs at least one year.</p>}
            <p className="form-note">
              Portfolio excess · SPY{" "}
              {report.excess_spy === null
                ? "—"
                : `${number(String(Number(report.excess_spy) * 100))} pp`}{" "}
              · QQQ{" "}
              {report.excess_qqq === null
                ? "—"
                : `${number(String(Number(report.excess_qqq) * 100))} pp`}
            </p>
            <ReturnChart series={report.series} scenario={report.scenario} />
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
                      {report.scenario && <th>Without excluded stocks</th>}
                      <th>SPY</th>
                      <th>QQQ</th>
                    </tr>
                  </thead>
                  <tbody>
                    {report.series.map((p, i) => (
                      <tr key={p.date}>
                        <td>{p.date}</td>
                        <td>{number(p.value)}</td>
                        <td>{percent(p.portfolio)}</td>
                        {report.scenario && (
                          <td>
                            {percent(
                              report.scenario.series[i]?.portfolio ?? null,
                            )}
                          </td>
                        )}
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
      </section>
    </>
  );
}
function ReturnChart({
  series: actual,
  scenario,
}: {
  series: Point[];
  scenario?: Report | null;
}) {
  const series = actual.map((p, i) => ({
    ...p,
    scenario: scenario?.series[i]?.portfolio ?? null,
  }));
  const keys = ["portfolio", "SPY", "QQQ", "scenario"] as const;
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
        {scenario && (
          <>
            {" "}
            / <span className="scenario-key">Without excluded stocks</span>
          </>
        )}
      </figcaption>
      <svg
        viewBox="0 0 800 240"
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
        <text x="58" y="229">
          {actual[0]?.date}
        </text>
        <text x="795" y="229" textAnchor="end">
          {actual.at(-1)?.date}
        </text>
        {keys.map(
          (k, index) =>
            series.every((p) => p[k] !== null) && (
              <polyline
                key={k}
                className={`${k.toLowerCase()}-line`}
                fill="none"
                strokeWidth="2"
                strokeDasharray={
                  index === 1
                    ? "7 4"
                    : index === 2
                      ? "2 4"
                      : index === 3
                        ? "10 3 2 3"
                        : undefined
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
