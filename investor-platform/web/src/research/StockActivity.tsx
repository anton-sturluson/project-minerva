import { useCallback, useEffect, useId, useRef, useState } from "react";
import { api, errorMessage } from "../api";
import { number, percent, quarterLabel } from "../format";

type Contributor = {
  slug: string;
  name: string;
  kind: string;
  previous_quantity: string;
  current_quantity: string;
  previous_weight: string;
  current_weight: string;
  weight_change_pp: string;
  quarter_end_price_usd: string | null;
  price_as_of: string | null;
  source_urls: string[];
};
type ActivityRow = {
  cusip: string;
  issuer: string;
  security_class: string;
  manager_count: number;
  average_weight_change_pp: string;
  contributors: Contributor[];
};
type Activity = {
  quarter: string | null;
  previous_quarter: string | null;
  available_quarters: string[];
  status: "available" | "unavailable";
  reason: string | null;
  included_managers: number;
  total_managers: number;
  excluded_managers: { slug: string; name: string; reason: string }[];
  increased: ActivityRow[];
  decreased: ActivityRow[];
};
type MarketContext = {
  status: "available" | "unavailable";
  reason: string | null;
  average_close_usd: string | null;
  low_close_usd: string | null;
  high_close_usd: string | null;
  first_session: string | null;
  last_session: string | null;
  session_count: number;
  source_urls: string[];
};
type MarketPrices = Record<string, MarketContext>;
const averageWeightHelp =
  "Equal mean of current 13F portfolio weights among managers in this direction.";
const weightChangeHelp =
  "Equal mean of portfolio weight changes among managers in this direction, in percentage points (pp): 2% to 3% is +1 pp.";
const averageCloseHelp =
  "Arithmetic mean of daily closing prices in the quarter; not a purchase price.";
const closingRangeHelp =
  "Minimum and maximum daily closing prices in the quarter; not intraday lows/highs or purchase prices.";
function unavailablePrice(reason: string): MarketContext {
  return {
    status: "unavailable",
    reason,
    average_close_usd: null,
    low_close_usd: null,
    high_close_usd: null,
    first_session: null,
    last_session: null,
    session_count: 0,
    source_urls: [],
  };
}
const labels: Record<string, string> = {
  new: "New position",
  exited: "Exited",
  increased: "Increased",
  decreased: "Decreased",
};
function shares(value: string) {
  return Number(value).toLocaleString("en-US", { maximumFractionDigits: 8 });
}
function percentagePoints(value: string) {
  return `${Number(value).toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
    signDisplay: "exceptZero",
  })} pp`;
}
type SortColumn = "issuer" | "manager_count" | "weight" | "weight_change";
const columns: { key: SortColumn; label: string; help?: string }[] = [
  { key: "issuer", label: "Security" },
  { key: "manager_count", label: "Managers" },
  { key: "weight", label: "Avg portfolio %", help: averageWeightHelp },
  {
    key: "weight_change",
    label: "Avg change (pp)",
    help: weightChangeHelp,
  },
];
function ContributorsTable({
  contributors,
  issuer,
}: {
  contributors: Contributor[];
  issuer: string;
}) {
  const [limit, setLimit] = useState(10);
  const ordered = [...contributors].sort(
    (left, right) =>
      Number(right.current_weight) - Number(left.current_weight) ||
      left.name.localeCompare(right.name, "en") ||
      left.slug.localeCompare(right.slug, "en"),
  );
  return (
    <>
      <div className="table-scroll" tabIndex={0}>
        <table
          className="activity-manager-table"
          aria-label={`${issuer} managers`}
        >
          <thead>
            <tr>
              <th scope="col">Manager / change</th>
              <th scope="col" className="number">
                Shares
              </th>
              <th
                scope="col"
                className="number"
                title="Share of this manager's reported 13F portfolio, previous quarter to current quarter."
              >
                13F weight: before → after
              </th>
              <th
                scope="col"
                className="number"
                title="Portfolio weight difference in percentage points: 2% to 3% is +1 pp."
              >
                Weight change (pp)
              </th>
            </tr>
          </thead>
          <tbody>
            {ordered.slice(0, limit).map((manager) => (
              <tr key={manager.slug}>
                <th scope="row">
                  {manager.name}
                  <small>{labels[manager.kind] ?? manager.kind}</small>
                </th>
                <td className="number">
                  {shares(manager.previous_quantity)} →{" "}
                  {shares(manager.current_quantity)}
                </td>
                <td className="number">
                  {percent(manager.previous_weight)} →{" "}
                  {percent(manager.current_weight)}
                </td>
                <td className="number">
                  {percentagePoints(manager.weight_change_pp)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {contributors.length > 10 && (
        <div
          className="activity-pagination"
          aria-label={`${issuer} manager pages`}
        >
          <span>
            {Math.min(limit, contributors.length)} of {contributors.length}{" "}
            managers
          </span>
          {limit < contributors.length && (
            <button
              onClick={() =>
                setLimit(Math.min(limit + 10, contributors.length))
              }
            >
              Show 10 more
            </button>
          )}
          {limit > 10 && (
            <button onClick={() => setLimit(10)}>Show fewer</button>
          )}
        </div>
      )}
    </>
  );
}

function StockRow({
  row,
  averageWeight,
  market,
  retryMarket,
}: {
  row: ActivityRow;
  averageWeight: number;
  market: MarketContext | undefined;
  retryMarket: (cusip: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const panelId = useId();
  return (
    <>
      <tr className="activity-stock-row">
        <td>
          <button
            className="activity-stock-toggle"
            aria-expanded={expanded}
            aria-controls={panelId}
            onClick={() => setExpanded(!expanded)}
          >
            <span aria-hidden="true">{expanded ? "▾ " : "▸ "}</span>
            {row.issuer}
          </button>
          <small>
            {row.security_class} · {row.cusip}
          </small>
        </td>
        <td className="number">{row.manager_count}</td>
        <td className="number">{percent(String(averageWeight))}</td>
        <td className="number">
          {percentagePoints(row.average_weight_change_pp)}
        </td>
        <td
          className="number activity-market-price"
          title={market?.reason ?? averageCloseHelp}
        >
          {!market ? (
            "Loading…"
          ) : market.status === "available" ? (
            `$${number(market.average_close_usd)}`
          ) : (
            <>
              Unavailable{" "}
              <button
                onClick={() => retryMarket(row.cusip)}
                aria-label={`Retry prices for ${row.issuer}`}
              >
                Retry
              </button>
            </>
          )}
        </td>
        <td className="number" title={closingRangeHelp}>
          {market?.status === "available"
            ? `$${number(market.low_close_usd)} – $${number(market.high_close_usd)}`
            : "—"}
        </td>
      </tr>
      <tr className="activity-expanded-row" hidden={!expanded}>
        <td colSpan={6} id={panelId}>
          {expanded && (
            <ContributorsTable
              contributors={row.contributors}
              issuer={row.issuer}
            />
          )}
        </td>
      </tr>
    </>
  );
}

function RankedActivity({
  title,
  rows,
  prices,
  reportVisible,
  retryMarket,
}: {
  title: string;
  rows: ActivityRow[];
  prices: MarketPrices;
  reportVisible: (title: string, cusips: string[]) => void;
  retryMarket: (cusip: string) => void;
}) {
  const [limit, setLimit] = useState(10);
  const [sort, setSort] = useState<{
    column: SortColumn;
    direction: "ascending" | "descending";
  }>({ column: "manager_count", direction: "descending" });
  const ordered = rows
    .map((row) => ({
      ...row,
      averageWeight:
        row.contributors.reduce(
          (sum, manager) => sum + Number(manager.current_weight),
          0,
        ) / row.contributors.length,
    }))
    .sort((left, right) => {
      const comparison =
        sort.column === "issuer"
          ? left.issuer.localeCompare(right.issuer, "en", {
              sensitivity: "base",
            })
          : sort.column === "manager_count"
            ? left.manager_count - right.manager_count
            : sort.column === "weight"
              ? left.averageWeight - right.averageWeight
              : Number(left.average_weight_change_pp) -
                Number(right.average_weight_change_pp);
      return (
        (sort.direction === "descending" ? -comparison : comparison) ||
        left.cusip.localeCompare(right.cusip) ||
        left.security_class.localeCompare(right.security_class)
      );
    });
  const visible = ordered.slice(0, limit);
  const visibleKey = visible.map((row) => row.cusip).join(",");
  useEffect(() => {
    reportVisible(title, visibleKey ? visibleKey.split(",") : []);
  }, [reportVisible, title, visibleKey]);
  function changeSort(column: SortColumn) {
    setLimit(10);
    setSort({
      column,
      direction:
        sort.column === column
          ? sort.direction === "descending"
            ? "ascending"
            : "descending"
          : column === "issuer"
            ? "ascending"
            : "descending",
    });
  }
  return (
    <section className="research-change-group" aria-label={title}>
      <h4>
        {title} <small>{rows.length} stocks</small>
      </h4>
      {rows.length === 0 ? (
        <p>No reported quantity changes in this direction.</p>
      ) : (
        <div className="table-scroll" tabIndex={0}>
          <table
            className="stock-activity-table"
            aria-label={`${title} stocks`}
          >
            <thead>
              <tr>
                {columns.map((column) => (
                  <th
                    key={column.key}
                    scope="col"
                    title={column.help}
                    className={column.key === "issuer" ? undefined : "number"}
                    aria-sort={
                      sort.column === column.key ? sort.direction : "none"
                    }
                  >
                    <button
                      aria-description={column.help}
                      onClick={() => changeSort(column.key)}
                    >
                      {column.label}{" "}
                      <span aria-hidden="true">
                        {sort.column === column.key
                          ? sort.direction === "descending"
                            ? "↓"
                            : "↑"
                          : "↕"}
                      </span>
                    </button>
                  </th>
                ))}
                <th scope="col" className="number" title={averageCloseHelp}>
                  Quarter avg close
                </th>
                <th scope="col" className="number" title={closingRangeHelp}>
                  Closing range
                </th>
              </tr>
            </thead>
            <tbody>
              {visible.map((row) => (
                <StockRow
                  key={`${row.cusip}|${row.security_class}`}
                  row={row}
                  averageWeight={row.averageWeight}
                  market={prices[row.cusip]}
                  retryMarket={retryMarket}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
      {rows.length > 10 && (
        <div
          className="activity-pagination"
          aria-label={`${title} stock pages`}
        >
          <span>
            {Math.min(limit, rows.length)} of {rows.length} stocks
          </span>
          {limit < rows.length && (
            <button onClick={() => setLimit(Math.min(limit + 10, rows.length))}>
              Show 10 more
            </button>
          )}
          {limit > 10 && (
            <button onClick={() => setLimit(10)}>Show fewer</button>
          )}
        </div>
      )}
    </section>
  );
}

function ActivityTables({ data }: { data: Activity }) {
  const [visible, setVisible] = useState<Record<string, string[]>>({});
  const [prices, setPrices] = useState<MarketPrices>({});
  const pending = useRef(new Set<string>());
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  const reportVisible = useCallback((title: string, cusips: string[]) => {
    setVisible((previous) => ({ ...previous, [title]: cusips }));
  }, []);
  const visibleKey = [...new Set(Object.values(visible).flat())]
    .sort()
    .join(",");
  useEffect(() => {
    const missing = visibleKey
      .split(",")
      .filter(
        (cusip) => cusip && !prices[cusip] && !pending.current.has(cusip),
      );
    for (let start = 0; start < missing.length; start += 20) {
      const batch = missing.slice(start, start + 20);
      batch.forEach((cusip) => pending.current.add(cusip));
      api<{ quarter: string; prices: MarketPrices }>(
        `/research/activity/market-context?quarter=${data.quarter}&cusips=${batch.join(",")}`,
        undefined,
        45000,
      ).then(
        (response) => {
          if (!mounted.current) return;
          const received: MarketPrices = {};
          batch.forEach((cusip) => {
            received[cusip] =
              response.quarter === data.quarter && response.prices[cusip]
                ? response.prices[cusip]
                : unavailablePrice("Quarter prices unavailable");
            pending.current.delete(cusip);
          });
          setPrices((previous) => ({ ...previous, ...received }));
        },
        (failure) => {
          if (!mounted.current) return;
          const unavailable: MarketPrices = {};
          batch.forEach((cusip) => {
            pending.current.delete(cusip);
            unavailable[cusip] = unavailablePrice(errorMessage(failure));
          });
          setPrices((previous) => ({ ...previous, ...unavailable }));
        },
      );
    }
  }, [visibleKey, prices, data.quarter]);
  function retryMarket(cusip: string) {
    setPrices((previous) => {
      const updated = { ...previous };
      delete updated[cusip];
      return updated;
    });
  }
  return (
    <>
      <RankedActivity
        title="Most increased"
        rows={data.increased}
        prices={prices}
        reportVisible={reportVisible}
        retryMarket={retryMarket}
      />
      <RankedActivity
        title="Most decreased"
        rows={data.decreased}
        prices={prices}
        reportVisible={reportVisible}
        retryMarket={retryMarket}
      />
    </>
  );
}

export function StockActivity() {
  const [data, setData] = useState<Activity | null>(null);
  const [quarter, setQuarter] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    api<Activity>(
      `/research/activity${quarter ? `?quarter=${encodeURIComponent(quarter)}` : ""}`,
    ).then(
      (response) => {
        if (active) {
          setData(response);
          setLoading(false);
        }
      },
      (failure) => {
        if (active) {
          setError(errorMessage(failure));
          setLoading(false);
        }
      },
    );
    return () => {
      active = false;
    };
  }, [quarter, retry]);
  return (
    <section aria-labelledby="stock-activity-heading">
      <h3 id="stock-activity-heading">Stock activity</h3>
      {data && data.available_quarters.length > 0 && (
        <label>
          Report quarter{" "}
          <select
            value={quarter || data.quarter || ""}
            onChange={(event) => setQuarter(event.target.value)}
          >
            {data.available_quarters.map((day) => (
              <option key={day} value={day}>
                {quarterLabel(day)}
              </option>
            ))}
          </select>
        </label>
      )}
      {loading && <p role="status">Loading stock activity…</p>}
      {error && (
        <div className="error" role="alert">
          {error}
          <br />
          <button onClick={() => setRetry(retry + 1)}>Try again</button>
        </div>
      )}
      {!loading && !error && data && (
        <>
          {data.quarter && data.previous_quarter && (
            <p>
              {quarterLabel(data.quarter)} compared with{" "}
              {quarterLabel(data.previous_quarter)}
            </p>
          )}
          <p>
            {data.included_managers} of {data.total_managers} managers included.
          </p>
          {data.excluded_managers.length > 0 && (
            <details className="activity-coverage">
              <summary>
                Excluded managers ({data.excluded_managers.length})
              </summary>
              <ul>
                {data.excluded_managers.map((manager) => (
                  <li key={manager.slug}>
                    <strong>{manager.name}</strong>: {manager.reason}
                  </li>
                ))}
              </ul>
            </details>
          )}
          {data.status === "unavailable" ? (
            <p role="status">Stock activity unavailable: {data.reason}</p>
          ) : (
            <ActivityTables key={data.quarter} data={data} />
          )}
        </>
      )}
    </section>
  );
}
