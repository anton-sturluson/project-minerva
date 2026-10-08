import { useEffect, useState } from "react";
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
function RankedActivity({
  title,
  rows,
}: {
  title: string;
  rows: ActivityRow[];
}) {
  const [showAll, setShowAll] = useState(false);
  const [sort, setSort] = useState<{
    column: SortColumn;
    direction: "ascending" | "descending";
  }>({ column: "weight", direction: "descending" });
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
  const visible = showAll ? ordered : ordered.slice(0, 20);
  function changeSort(column: SortColumn) {
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
        {title}{" "}
        <small>
          {rows.length > 20 && !showAll
            ? `Top 20 of ${rows.length}`
            : `${rows.length} stocks`}
        </small>
      </h4>
      {rows.length === 0 ? (
        <p>No reported quantity changes in this direction.</p>
      ) : (
        <div className="table-scroll" tabIndex={0}>
          <table className="stock-activity-table">
            <thead>
              <tr>
                {columns.map((column) => (
                  <th
                    key={column.key}
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
              {visible.map((row) => (
                <tr key={`${row.cusip}|${row.security_class}`}>
                  <td>
                    <details>
                      <summary>
                        {row.issuer}
                        <small>
                          {row.security_class} · {row.cusip}
                        </small>
                      </summary>
                      <ul className="activity-contributors">
                        {row.contributors.map((manager) => (
                          <li key={manager.slug}>
                            <strong>{manager.name}</strong>
                            <p>
                              {labels[manager.kind] ?? manager.kind} ·{" "}
                              {percent(manager.previous_weight)} →{" "}
                              {percent(manager.current_weight)} ·{" "}
                              {percentagePoints(manager.weight_change_pp)}
                            </p>
                            <p>
                              Reported shares:{" "}
                              {number(manager.previous_quantity, 0)} →{" "}
                              {number(manager.current_quantity, 0)}
                            </p>
                            <div className="research-links">
                              {manager.source_urls.map((url, index) => (
                                <a
                                  key={url}
                                  href={url}
                                  target="_blank"
                                  rel="noreferrer"
                                >
                                  Filing source {index + 1}
                                </a>
                              ))}
                            </div>
                          </li>
                        ))}
                      </ul>
                    </details>
                  </td>
                  <td className="number">{row.manager_count}</td>
                  <td className="number">
                    {percent(String(row.averageWeight))}
                  </td>
                  <td className="number">
                    {percentagePoints(row.average_weight_change_pp)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {rows.length > 20 && (
        <p>
          <button onClick={() => setShowAll(!showAll)} aria-expanded={showAll}>
            {showAll ? "Show top 20" : "Show all"}
          </button>
        </p>
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
          <p className="form-note">
            Default order: average current 13F weight, largest first. Select any
            column heading to change the order.
          </p>
          <details>
            <summary>How activity is measured</summary>
            <p className="form-note">
              Changes compare quarter-end share quantities, not individual
              trades. Share changes can reflect stock splits. Price changes
              alone do not count as increased or decreased positions. Weights
              include all disclosed 13F positions, not the whole fund. Rankings
              exclude options and principal positions; fund shares can be
              included. Average weight changes use only contributing managers
              and can have a different sign from share changes. Changes are in
              percentage points (pp). Average 13F weight is the equal-weight
              mean of current portfolio weights among contributing managers.
            </p>
          </details>
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
