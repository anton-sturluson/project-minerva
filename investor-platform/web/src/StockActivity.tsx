import { useEffect, useId, useState } from "react";
import { api, errorMessage } from "./api";
import { number, percent, quarterLabel } from "./format";

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
const columns: { key: SortColumn; label: string }[] = [
  { key: "issuer", label: "Security" },
  { key: "manager_count", label: "Managers" },
  { key: "weight", label: "Average 13F weight" },
  { key: "weight_change", label: "Average weight change" },
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
              <th scope="col" className="number">
                13F weight
              </th>
              <th scope="col" className="number">
                Weight change
              </th>
              <th
                scope="col"
                className="number"
                title="Reported quarter-end value per share; not a purchase price."
              >
                Quarter-end price
              </th>
              <th scope="col">Sources</th>
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
                <td className="number">
                  {manager.quarter_end_price_usd === null
                    ? "Unavailable"
                    : `$${number(manager.quarter_end_price_usd)}`}
                  {manager.price_as_of && <small>{manager.price_as_of}</small>}
                </td>
                <td>
                  <div className="research-links">
                    {manager.source_urls.map((url, index) => (
                      <a key={url} href={url} target="_blank" rel="noreferrer">
                        Filing source {index + 1}
                      </a>
                    ))}
                  </div>
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
}: {
  row: ActivityRow;
  averageWeight: number;
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
      </tr>
      <tr className="activity-expanded-row" hidden={!expanded}>
        <td colSpan={4} id={panelId}>
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
}: {
  title: string;
  rows: ActivityRow[];
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
                    className={column.key === "issuer" ? undefined : "number"}
                    aria-sort={
                      sort.column === column.key ? sort.direction : "none"
                    }
                  >
                    <button onClick={() => changeSort(column.key)}>
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
              </tr>
            </thead>
            <tbody>
              {ordered.slice(0, limit).map((row) => (
                <StockRow
                  key={`${row.cusip}|${row.security_class}`}
                  row={row}
                  averageWeight={row.averageWeight}
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
            <>
              <RankedActivity
                key={`${data.quarter}:increased`}
                title="Most increased"
                rows={data.increased}
              />
              <RankedActivity
                key={`${data.quarter}:decreased`}
                title="Most decreased"
                rows={data.decreased}
              />
            </>
          )}
        </>
      )}
    </section>
  );
}
