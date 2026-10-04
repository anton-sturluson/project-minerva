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
import { StockExclusions } from "./StockExclusions";
import { BenchmarkReturn, YearlyPerformance } from "./YearlyPerformance";
import { today, type Ledger } from "./records";

type Scope = "stocks" | "account";

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
  scope?: Scope;
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
  receivables?: string;
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
  const d = new Date(today() + "T12:00:00Z");
  d.setUTCDate(d.getUTCDate() - 1);
  return d.toISOString().slice(0, 10);
};

type Shortcut = "ytd" | "year" | "history";

const shortcutDates = (ledger: Ledger, through: string, shortcut: Shortcut) => {
  const first = ledger.entries[0]?.effective_date ?? through;
  if (shortcut === "history") return { from: first, anchor: undefined };
  const boundary = new Date(through + "T12:00:00Z");
  if (shortcut === "ytd") {
    boundary.setUTCFullYear(Number(today().slice(0, 4)) - 1, 11, 31);
  } else {
    const month = boundary.getUTCMonth();
    boundary.setUTCFullYear(boundary.getUTCFullYear() - 1);
    if (boundary.getUTCMonth() !== month) boundary.setUTCDate(0); // Feb 29 -> Feb 28.
  }
  const anchor = boundary.toISOString().slice(0, 10);
  // Fetch enough history to select the close on/before a holiday or weekend boundary.
  boundary.setUTCDate(boundary.getUTCDate() - 7);
  const fetchFrom = boundary.toISOString().slice(0, 10);
  return { from: first > fetchFrom ? first : fetchFrom, anchor };
};

export function Tracker({
  account,
  ledger,
}: {
  account: Account;
  ledger: Ledger;
}) {
  const [scope, setScope] = useState<Scope>("stocks");
  const [baseline, setBaseline] = useState<Baseline>("history");
  const [start, setStart] = useState(
    ledger.entries[0]?.effective_date ?? yesterday(),
  );
  const [end, setEnd] = useState(yesterday());
  const [anchor, setAnchor] = useState<string | undefined>();
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
      measurement: Scope = "stocks",
      anchor?: string,
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
              scope: measurement,
              ...(anchor ? { anchor_date: anchor } : {}),
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
        if (version === generation.current) {
          setReport(r);
          if (anchor) setStart(r.start);
        }
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
    // Always open the full recorded history; recent comparisons are explicitly selected.
    const through = yesterday();
    const from = ledger.entries[0]?.effective_date ?? through;
    setAnchor(undefined);
    setScope("stocks");
    setBaseline("history");
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
      void compare(from, through);
    return () => {
      generation.current += 1;
    };
  }, [account.base_currency, account.reconstruction, ledger, compare]);
  function submit(e: FormEvent) {
    e.preventDefault();
    void compare(start, end, excluded, baseline, scope, anchor);
  }
  function choosePeriod(shortcut: Shortcut) {
    const through = yesterday();
    const basis: Baseline = shortcut === "history" ? "history" : "recorded";
    const { from, anchor } = shortcutDates(ledger, through, shortcut);
    setAnchor(anchor);
    setBaseline(basis);
    setStart(from);
    setEnd(through);
    setExcluded([]);
    setReport(null);
    void compare(from, through, [], basis, scope, anchor);
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
          {scope === "stocks"
            ? "Stocks vs. the market"
            : "Account vs. the market"}
        </h2>
        <p className="period-shortcuts">
          <button
            type="button"
            disabled={
              busy || !ledger.entries.length || account.base_currency !== "USD"
            }
            onClick={() => choosePeriod("ytd")}
          >
            YTD
          </button>{" "}
          <button
            type="button"
            disabled={
              busy || !ledger.entries.length || account.base_currency !== "USD"
            }
            onClick={() => choosePeriod("year")}
          >
            1 year
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
        <form className="entry-form performance-controls" onSubmit={submit}>
          <label>
            Measure
            <select
              aria-label="Performance measure"
              value={scope}
              disabled={busy}
              onChange={(e) => {
                const next = e.target.value as Scope;
                setScope(next);
                setReport(null);
                void compare(start, end, excluded, baseline, next, anchor);
              }}
            >
              <option value="stocks">Stocks only</option>
              <option value="account">Whole account</option>
            </select>
          </label>
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
                setAnchor(undefined);
                setStart(e.target.value);
                setBaseline(
                  e.target.value === ledger.entries[0]?.effective_date
                    ? "history"
                    : "recorded",
                );
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
                setAnchor(undefined);
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
            <StockExclusions
              stocks={securities.filter(
                (security) =>
                  baseline !== "recorded" ||
                  !report?.security_ids ||
                  report.security_ids.includes(security.id),
              )}
              selected={excluded}
              disabled={busy}
              onChange={(ids) => {
                setExcluded(ids);
                setReport((current) =>
                  current
                    ? { ...current, scenario: null, scenario_error: null }
                    : null,
                );
                setError("");
              }}
            />
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
            {report.scope === "stocks" && (
              <p className="form-note">
                Estimated · stocks only · gross dividends included.
              </p>
            )}
            {report.warnings.slice(0, 1).map((w) => (
              <p key={w} role="alert" className="error">
                {w} Portfolio return is withheld.
              </p>
            ))}
            {report.warnings.length > 1 && (
              <details>
                <summary>
                  Other reconciliation checks ({report.warnings.length - 1})
                </summary>
                <ul>
                  {report.warnings.slice(1).map((w) => (
                    <li key={w}>{w}</li>
                  ))}
                </ul>
              </details>
            )}
            <p>
              <span>
                {report.scope === "stocks"
                  ? "Stock value (USD)"
                  : report.provisional
                    ? "Estimated closing value (USD)"
                    : "Closing value (USD)"}
              </span>{" "}
              <strong>{number(report.value)}</strong>
              {Number(report.receivables ?? 0) > 0 && (
                <>
                  {" "}
                  · includes {number(report.receivables!)} in unpaid dividends
                </>
              )}
            </p>
            {report.scenario_error && (
              <p role="alert" className="error">
                {report.scenario_error}.
              </p>
            )}
            {report.scenario && (
              <p className="form-note">
                Without{" "}
                {report.scenario.excluded
                  .map((s) => `${s.ticker} · ${s.exchange}`)
                  .join(", ")}{" "}
                ·{" "}
                {report.scope === "stocks"
                  ? "remaining stocks only"
                  : "unused cash retained"}
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
                    <th
                      className="number"
                      title="Annualized return; requires at least one year"
                    >
                      CAGR
                    </th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td>
                      {report.scope === "stocks"
                        ? "Stock portfolio return"
                        : report.provisional
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
                    <td className="number">
                      <BenchmarkReturn
                        value={report.SPY}
                        portfolio={report.return}
                        name="S&P 500"
                      />
                    </td>
                    <td className="number">
                      <BenchmarkReturn
                        value={report.cagr?.SPY ?? null}
                        portfolio={report.cagr?.portfolio ?? null}
                        name="S&P 500 CAGR"
                      />
                    </td>
                  </tr>
                  <tr>
                    <td>Nasdaq-100 · QQQ</td>
                    <td className="number">
                      <BenchmarkReturn
                        value={report.QQQ}
                        portfolio={report.return}
                        name="Nasdaq-100"
                      />
                    </td>
                    <td className="number">
                      <BenchmarkReturn
                        value={report.cagr?.QQQ ?? null}
                        portfolio={report.cagr?.portfolio ?? null}
                        name="Nasdaq-100 CAGR"
                      />
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
            <ReturnChart series={report.series} scenario={report.scenario} />
            <YearlyPerformance report={report} requestedEnd={end} />
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
  const elapsed =
    (Date.parse(actual.at(-1)!.date) - Date.parse(actual[0].date)) / 86400000;
  const bucket = (date: string) =>
    elapsed > 730
      ? date.slice(0, 4)
      : elapsed > 180
        ? `${date.slice(0, 4)}-${Math.floor((Number(date.slice(5, 7)) - 1) / 3)}`
        : date.slice(0, 7);
  const ticks = actual.flatMap((point, index) =>
    index > 0 &&
    index < actual.length - 1 &&
    bucket(point.date) !== bucket(actual[index - 1].date)
      ? [
          {
            index,
            date: point.date,
            label:
              elapsed > 730
                ? point.date.slice(0, 4)
                : new Date(point.date + "T12:00:00Z").toLocaleDateString(
                    "en-US",
                    { month: "short", year: "2-digit", timeZone: "UTC" },
                  ),
          },
        ]
      : [],
  );
  if (!ticks.length && actual.length > 3) {
    for (const fraction of [1 / 3, 2 / 3]) {
      const index = Math.floor((actual.length - 1) * fraction);
      if (!ticks.some((tick) => tick.index === index))
        ticks.push({
          index,
          date: actual[index].date,
          label: actual[index].date.slice(5),
        });
    }
  }
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
        viewBox="0 0 800 265"
        role="img"
        aria-label={`Cumulative portfolio and benchmark returns from ${actual[0]?.date} to ${actual.at(-1)?.date}`}
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
        <g className="chart-dates" aria-label="Chart dates">
          {ticks.map((tick) => {
            const x = 58 + (tick.index / (actual.length - 1)) * 737;
            return (
              <g key={tick.date}>
                <title>{tick.date}</title>
                <line
                  x1={x}
                  x2={x}
                  y1="200"
                  y2="208"
                  stroke="currentColor"
                  opacity="0.4"
                />
                <text
                  x={x}
                  y="226"
                  textAnchor={x < 100 ? "start" : x > 750 ? "end" : "middle"}
                >
                  {tick.label}
                </text>
              </g>
            );
          })}
          <text x="58" y="256">
            {actual[0]?.date}
          </text>
          <text x="795" y="256" textAnchor="end">
            {actual.at(-1)?.date}
          </text>
        </g>
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
