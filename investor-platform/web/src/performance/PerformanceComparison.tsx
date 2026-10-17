import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";
import { errorMessage, type Account } from "../api";
import { number, percent } from "../format";
import { StockExclusions } from "./StockExclusions";
import { BenchmarkReturn, YearlyPerformance } from "./YearlyPerformance";
import { ReturnChart } from "./ReturnChart";
import { marketDataThroughDate, newYorkToday } from "../marketDates";
import { type Ledger } from "../ledger/ledger";
import {
  fetchPerformance,
  type PerformanceRequest,
  type PerformanceScope,
  type PerformanceBaseline,
  type BenchmarkMode,
  type PerformanceReport,
} from "./performanceApi";

type Shortcut = "ytd" | "year" | "history";

const shortcutDates = (ledger: Ledger, through: string, shortcut: Shortcut) => {
  const first = ledger.entries[0]?.effective_date ?? through;
  if (shortcut === "history") return { from: first, anchor: undefined };
  const boundary = new Date(through + "T12:00:00Z");
  if (shortcut === "ytd") {
    boundary.setUTCFullYear(Number(newYorkToday().slice(0, 4)) - 1, 11, 31);
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

export function PerformanceComparison({
  account,
  ledger,
}: {
  account: Account;
  ledger: Ledger;
}) {
  const standardAccount =
    account.reconstruction?.cash_method === "purchase_shortfall" ||
    account.reconstruction?.cash_method === "recorded";
  const canEstimate =
    standardAccount ||
    (account.reconstruction?.funding_status === "inferred" &&
      account.reconstruction.opening_cash != null);
  const [scope, setScope] = useState<PerformanceScope>(
    canEstimate ? "account" : "stocks",
  );
  const [benchmarkMode, setBenchmarkMode] = useState<BenchmarkMode>(
    canEstimate ? "funded_hold" : "buy_hold",
  );
  const [baseline, setBaseline] = useState<PerformanceBaseline>("history");
  const [start, setStart] = useState(
    ledger.entries[0]?.effective_date ?? marketDataThroughDate(),
  );
  const [end, setEnd] = useState(marketDataThroughDate());
  const [anchor, setAnchor] = useState<string | undefined>();
  const [excluded, setExcluded] = useState<string[]>([]);
  const securities = [
    ...new Map(
      ledger.entries
        .filter((e) => e.security && e.effective_date <= end)
        .map((e) => [e.security!.id, e.security!]),
    ).values(),
  ];
  const [report, setReport] = useState<PerformanceReport | null>(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  const generation = useRef(0);
  const lastComparison = useRef<PerformanceRequest | null>(null);
  const compare = useCallback(
    async (request: PerformanceRequest) => {
      const comparison: PerformanceRequest = {
        ...request,
        scope: standardAccount ? "account" : request.scope,
      };
      lastComparison.current = comparison;
      const version = ++generation.current;
      setBusy(true);
      setError("");
      setReport((current) =>
        current ? { ...current, scenario: null, scenario_error: null } : null,
      );
      try {
        const r = await fetchPerformance(account.id, comparison);
        if (version === generation.current) {
          setReport(r);
          if (request.anchor_date) setStart(r.start);
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
    [account.id, standardAccount],
  );
  useEffect(() => {
    if (standardAccount && lastComparison.current) {
      setScope("account");
      setReport(null);
      void compare(lastComparison.current);
      return () => {
        generation.current += 1;
      };
    }
    // Open full history initially; purchase-funded ledger refreshes retain the comparison.
    const through = marketDataThroughDate();
    const from = ledger.entries[0]?.effective_date ?? through;
    setAnchor(undefined);
    const initialMode = canEstimate ? "funded_hold" : "buy_hold";
    const initialScope = canEstimate ? "account" : "stocks";
    setScope(initialScope);
    setBenchmarkMode(initialMode);
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
      void compare({
        start: from,
        end: through,
        exclude_security_ids: [],
        baseline: "history",
        scope: initialScope,
        anchor_date: undefined,
        benchmark_mode: initialMode,
      });
    return () => {
      generation.current += 1;
    };
  }, [
    account.base_currency,
    account.reconstruction,
    canEstimate,
    standardAccount,
    ledger,
    compare,
  ]);
  function submit(e: FormEvent) {
    e.preventDefault();
    void compare({
      start: start,
      end: end,
      exclude_security_ids: excluded,
      baseline: baseline,
      scope: scope,
      anchor_date: anchor,
      benchmark_mode: benchmarkMode,
    });
  }
  function choosePeriod(shortcut: Shortcut) {
    const through = marketDataThroughDate();
    const basis: PerformanceBaseline =
      shortcut === "history" ? "history" : "recorded";
    const { from, anchor } = shortcutDates(ledger, through, shortcut);
    setAnchor(anchor);
    setBaseline(basis);
    setStart(from);
    setEnd(through);
    setExcluded([]);
    setReport(null);
    void compare({
      start: from,
      end: through,
      exclude_security_ids: [],
      baseline: basis,
      scope: scope,
      anchor_date: anchor,
      benchmark_mode: benchmarkMode,
    });
  }
  const showInvestedValue =
    report?.scope === "stocks" &&
    report.benchmark_mode === "matched" &&
    !!report.matched_benchmarks;
  const modeledPortfolio =
    report?.scope === "account" &&
    (standardAccount || !!report.funding_estimate);
  const cashMethod = report?.cash_method ?? account.reconstruction?.cash_method;
  const recordedCash = cashMethod === "recorded";
  const fundingDescription = recordedCash
    ? "Whole-account time-weighted return using recorded cash entries. Funding reconciliation may still be incomplete."
    : standardAccount
      ? "Whole-account time-weighted return. Inferred deposits cover purchase cash shortfalls; recorded sale proceeds remain as cash. Cash history is unverified. Dividends require recorded income."
      : "Estimated stocks plus cash. Deposits cover purchase shortfalls after available cash, sale proceeds, and estimated dividends. The imported opening cash is ignored.";
  const showEstimatedValue =
    report?.benchmark_mode === "funded_hold" && !!report.benchmark_values;
  const showValue = showInvestedValue || showEstimatedValue;
  const benchmarkValues = showEstimatedValue
    ? report?.benchmark_values
    : report?.matched_benchmarks;
  return (
    <>
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
          {!standardAccount && (
            <label>
              Measure
              <select
                aria-label="Performance measure"
                value={scope}
                disabled={busy}
                onChange={(e) => {
                  const next = e.target.value as PerformanceScope;
                  const nextExcluded =
                    canEstimate && next === "account" ? [] : excluded;
                  setScope(next);
                  setExcluded(nextExcluded);
                  setReport(null);
                  void compare({
                    start: start,
                    end: end,
                    exclude_security_ids: nextExcluded,
                    baseline: baseline,
                    scope: next,
                    anchor_date: anchor,
                    benchmark_mode: benchmarkMode,
                  });
                }}
              >
                <option value="stocks">Stocks only</option>
                <option value="account">Whole account</option>
              </select>
            </label>
          )}
          <label>
            Index comparison
            <select
              aria-label="Index comparison"
              value={benchmarkMode}
              title={
                benchmarkMode === "funded_hold" && recordedCash
                  ? "Indexes invest recorded deposits at session closes and are never sold. Your portfolio uses the same calculation in both index comparisons."
                  : benchmarkMode === "funded_hold"
                    ? "Indexes invest the estimated purchase funding on each deposit date and are never sold. Your portfolio uses the same calculation in both index comparisons."
                    : benchmarkMode === "matched"
                      ? "Indexes match stock purchases and sales. Your portfolio calculation stays the same."
                      : "Indexes are bought at the start of the selected period and held. Your portfolio calculation stays the same."
              }
              disabled={
                busy ||
                !ledger.entries.length ||
                account.base_currency !== "USD"
              }
              onChange={(e) => {
                const next = e.target.value as BenchmarkMode;
                setBenchmarkMode(next);
                setReport(null);
                void compare({
                  start: start,
                  end: end,
                  exclude_security_ids: excluded,
                  baseline: baseline,
                  scope: scope,
                  anchor_date: anchor,
                  benchmark_mode: next,
                });
              }}
            >
              <option value="buy_hold">Buy and hold</option>
              {canEstimate ? (
                <option value="funded_hold">
                  {recordedCash ? "Match deposits" : "Match purchase funding"}
                </option>
              ) : (
                <option value="matched">Match buys &amp; sales</option>
              )}
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
                const from = e.target.value;
                const basis =
                  from === ledger.entries[0]?.effective_date
                    ? "history"
                    : "recorded";
                setStart(from);
                setBaseline(basis);
                if (standardAccount)
                  lastComparison.current = {
                    start: from,
                    end: end,
                    exclude_security_ids: [],
                    baseline: basis,
                    scope: "account",
                    anchor_date: undefined,
                    benchmark_mode: benchmarkMode,
                  };
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
              max={marketDataThroughDate()}
              onChange={(e) => {
                setAnchor(undefined);
                setEnd(e.target.value);
                if (standardAccount)
                  lastComparison.current = {
                    start: start,
                    end: e.target.value,
                    exclude_security_ids: [],
                    baseline: baseline,
                    scope: "account",
                    anchor_date: undefined,
                    benchmark_mode: benchmarkMode,
                  };
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
          {!(canEstimate && scope === "account") && securities.length > 0 && (
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
            {!showValue && (
              <p>
                <span title={modeledPortfolio ? fundingDescription : undefined}>
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
            )}
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
            {report.dividend_policy === "unrecorded_zero" && (
              <p
                className="form-note"
                title="Recorded dividends still count. Unrecorded dividends add no cash or receivable; this is a temporary account assumption."
              >
                Unrecorded dividends assumed zero
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
                    <th>Portfolio</th>
                    {showValue && (
                      <th
                        className="number"
                        title={
                          showEstimatedValue
                            ? "Indexes invest the estimated funding on each deposit date and are never sold. Portfolio value uses the selected measure."
                            : "Value still invested after matching purchases and sales; cash and exited proceeds are excluded"
                        }
                      >
                        {showEstimatedValue
                          ? "Estimated value (USD)"
                          : "Invested value (USD)"}
                      </th>
                    )}
                    <th className="number">Cumulative</th>
                    <th
                      className="number"
                      title="Annualized time-weighted return (ACT/365.25); requires at least one year"
                    >
                      CAGR
                    </th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td
                      title={modeledPortfolio ? fundingDescription : undefined}
                    >
                      {modeledPortfolio
                        ? "Your portfolio + cash"
                        : report.scope === "stocks"
                          ? "Stock portfolio return"
                          : report.provisional
                            ? "Estimated portfolio return"
                            : "Portfolio return"}
                    </td>
                    {showValue && (
                      <td className="number">{number(report.value)}</td>
                    )}
                    <td className="number">{percent(report.return)}</td>
                    <td className="number">
                      {percent(report.cagr?.portfolio ?? null)}
                    </td>
                  </tr>
                  {report.scenario && (
                    <tr>
                      <td>Without excluded stocks</td>
                      {showValue && (
                        <td className="number">
                          {number(report.scenario.value)}
                        </td>
                      )}
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
                    {showValue && (
                      <td className="number">
                        {number(benchmarkValues!.SPY.value)}
                      </td>
                    )}
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
                    {showValue && (
                      <td className="number">
                        {number(benchmarkValues!.QQQ.value)}
                      </td>
                    )}
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
            <ReturnChart
              series={report.series}
              scenario={report.scenario}
              benchmarkMode={report.benchmark_mode}
              cashMethod={cashMethod ?? undefined}
            />
            <YearlyPerformance report={report} requestedEnd={end} />
          </>
        )}
      </section>
    </>
  );
}
