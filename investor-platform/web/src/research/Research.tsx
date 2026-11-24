import { useEffect, useRef, useState } from "react";
import { DivergingBarChart } from "../components/DivergingBarChart";
import { securityLabel, useResearchSymbols } from "./securityLabels";
import { ChartRowLimit } from "./ChartRowLimit";
import { api, errorMessage } from "../api";
import { Economics } from "./Economics";
import { InstitutionalStockActivity } from "./InstitutionalStockActivity";
import { percent, quarterLabel } from "../format";

type Coverage = {
  quarters: number;
  first_quarter: string | null;
  last_quarter: string | null;
  continuous_decade: boolean;
};
type Manager = {
  slug: string;
  name: string;
  investor_names: string[];
  cik: string;
  website_url: string | null;
  letters_url: string | null;
  focus: string;
  history_start_year: number | null;
  history_source_url: string | null;
  source_urls: string[];
  notes?: string;
  aum_usd: string | null;
  aum_as_of: string | null;
  aum_source_url: string | null;
  aum_measurement:
    "regulatory_aum" | "firm_aum" | "verified_lower_bound" | null;
  coverage: Coverage;
  portfolio_company_count: number | null;
  portfolio_company_count_quarter: string | null;
};
type Filing = {
  quarter: string;
  filed_date: string;
  source_url: string;
};
type Detail = Manager & { filings: Filing[] };
type Change = {
  cusip: string;
  issuer: string;
  security_class: string;
  put_call: string;
  share_type: string;
  kind: string;
  category: "increased" | "decreased" | "unchanged";
  previous_quantity: string;
  current_quantity: string;
  quantity_change: string;
  current_value_usd: string;
  value_change_usd: string;
  previous_weight: string | null;
  current_weight: string | null;
  weight_change: string | null;
};
type Comparison = {
  quarter: string;
  previous_quarter: string;
  status: "available" | "unavailable";
  reason: string | null;
  source_urls: string[];
  changes: Change[];
  year?: number;
  year_to_date?: boolean;
};
const changeLabels: Record<string, string> = {
  new: "New position",
  exited: "Exited",
  increased: "Increased",
  decreased: "Reduced",
  unchanged: "Unchanged",
};
function quantity(value: string) {
  return Number(value).toLocaleString("en-US", { maximumFractionDigits: 4 });
}
function dollars(value: string, signed = false) {
  const amount = Number(value);
  const magnitude = Math.abs(amount);
  const millions = magnitude >= 1_000_000;
  const divisor = millions ? 1_000_000 : 1_000;
  const scaled =
    magnitude >= 1_000 ? Math.trunc(magnitude / divisor) : magnitude / divisor;
  const digits = scaled > 0 && scaled < 1 ? 3 : 0;
  const sign = amount < 0 ? "-" : signed && amount > 0 ? "+" : "";
  return `${sign}$${scaled.toLocaleString("en-US", { maximumFractionDigits: digits })}${millions ? "M" : "K"}`;
}
function exactDollars(value: string, signed = false) {
  return Number(value).toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
    signDisplay: signed ? "exceptZero" : "auto",
  });
}
function weightChange(value: string | null) {
  return value === null
    ? "Unavailable"
    : `${(Number(value) * 100).toLocaleString("en-US", { maximumFractionDigits: 2, minimumFractionDigits: 2, signDisplay: "exceptZero" })} pp`;
}
function weight(value: string | null) {
  return value === null ? "Unavailable" : percent(value);
}
function SourceLink({
  url,
  children,
}: {
  url: string;
  children: React.ReactNode;
}) {
  return (
    <a href={url} target="_blank" rel="noreferrer">
      {children}
    </a>
  );
}

function AumSummary({ manager }: { manager: Manager }) {
  const labels = {
    regulatory_aum: "Regulatory AUM",
    firm_aum: "Firm AUM",
    verified_lower_bound: "AUM lower bound",
  };
  if (!manager.aum_usd) return <p className="form-note">AUM not disclosed</p>;
  return (
    <p className="form-note">
      {manager.aum_measurement ? labels[manager.aum_measurement] : "AUM"}:{" "}
      <span title={exactDollars(manager.aum_usd)}>
        {dollars(manager.aum_usd)}
        {manager.aum_as_of && ` · ${manager.aum_as_of}`}
      </span>
      {manager.aum_source_url && (
        <>
          {" "}
          · <SourceLink url={manager.aum_source_url}>Source</SourceLink>
        </>
      )}
    </p>
  );
}

function ManagerWeightChart({ comparison }: { comparison: Comparison }) {
  const [search, setSearch] = useState("");
  const [order, setOrder] = useState("absolute");
  const [limit, setLimit] = useState(10);
  const shares = comparison.changes.filter(
    (change) => change.share_type === "SH" && !change.put_call,
  );
  const rows = shares
    .filter(
      (change) =>
        change.weight_change !== null &&
        Number.isFinite(Number(change.weight_change)) &&
        Number(change.weight_change) !== 0,
    )
    .map((change) => {
      const delta = Number(change.weight_change) * 100;
      return {
        id: `${change.cusip}|${change.put_call}|${change.share_type}`,
        change,
        left: Math.max(0, -delta),
        right: Math.max(0, delta),
      };
    });
  const matching = rows.filter(({ change }) =>
    `${change.issuer} ${change.security_class} ${change.cusip}`
      .toLowerCase()
      .includes(search.toLowerCase()),
  );
  const score = (row: (typeof rows)[number]) =>
    order === "increased"
      ? row.right
      : order === "decreased"
        ? row.left
        : Math.max(row.left, row.right);
  const visible = matching
    .sort((a, b) => score(b) - score(a) || a.id.localeCompare(b.id))
    .slice(0, limit);
  const symbols = useResearchSymbols(visible.map((row) => row.change.cusip));
  if (rows.length === 0)
    return (
      <p className="form-note">
        {shares.some((change) => change.weight_change === null)
          ? "Portfolio weight changes unavailable."
          : "No reported portfolio weight changes."}
      </p>
    );
  const domainMax = Math.max(
    2,
    Math.ceil(
      Math.max(...rows.map((row) => Math.max(row.left, row.right))) / 2,
    ) * 2,
  );
  return (
    <DivergingBarChart
      title="Portfolio weight changes"
      rows={visible.map((row) => ({
        id: row.id,
        ...securityLabel(row.change.issuer, symbols[row.change.cusip]?.symbol),
        left: row.left,
        right: row.right,
      }))}
      domainMax={domainMax}
      leftLabel="Weight decreased"
      rightLabel="Weight increased"
      unitLabel="Change in reported 13F weight (pp)"
      formatValue={(value, side) =>
        weightChange((side === "left" ? -value / 100 : value / 100).toString())
      }
      formatTick={(value) => String(value)}
      renderDetails={(selected) => {
        const { change } = rows.find((row) => row.id === selected.id)!;
        return (
          <>
            <p className="form-note">
              {quarterLabel(comparison.previous_quarter)} →{" "}
              {quarterLabel(comparison.quarter)} · {change.security_class} ·{" "}
              {change.cusip}
            </p>
            <dl className="chart-position-details">
              <div>
                <dt>Share-count change</dt>
                <dd>{changeLabels[change.kind] ?? change.kind}</dd>
              </div>
              <div>
                <dt>Shares</dt>
                <dd>
                  {quantity(change.previous_quantity)} →{" "}
                  {quantity(change.current_quantity)}
                </dd>
              </div>
              <div>
                <dt>Reported 13F weight</dt>
                <dd>
                  {weight(change.previous_weight ?? null)} →{" "}
                  {weight(change.current_weight)}
                </dd>
              </div>
              <div>
                <dt>Weight change</dt>
                <dd>{weightChange(change.weight_change)}</dd>
              </div>
            </dl>
            <div className="research-links">
              {comparison.source_urls.map((url, index) => (
                <SourceLink key={url} url={url}>
                  Filing {index + 1}
                </SourceLink>
              ))}
            </div>
          </>
        );
      }}
    >
      <div className="chart-controls">
        <label>
          Find a security
          <input
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </label>
        <label>
          Order
          <select
            aria-label="Chart order"
            value={order}
            onChange={(e) => setOrder(e.target.value)}
          >
            <option value="absolute">Largest weight changes</option>
            <option value="increased">Largest weight increases</option>
            <option value="decreased">Largest weight decreases</option>
          </select>
        </label>
        <ChartRowLimit value={limit} onChange={setLimit} />
        <span className="form-note">
          {Math.min(limit, matching.length)} of {matching.length}
        </span>
      </div>
    </DivergingBarChart>
  );
}

function QuarterlyChanges({
  changes,
  annual,
}: {
  changes: Change[];
  annual: boolean;
}) {
  const groups = ["increased", "decreased", "unchanged"] as const;
  return (
    <section
      aria-label={
        annual ? "Annual net position changes" : "Quarterly position changes"
      }
    >
      {groups.map((group) => {
        const rows = changes.filter((change) => change.category === group);
        return (
          <section
            key={group}
            className="research-change-group"
            aria-label={`Quantity ${group} positions`}
          >
            <h4>
              Quantity {group} <small>({rows.length})</small>
            </h4>
            {rows.length === 0 ? (
              <p className="form-note">No {group} positions.</p>
            ) : (
              <div className="table-scroll" tabIndex={0}>
                <table className="research-changes-table">
                  <thead>
                    <tr>
                      <th>Security</th>
                      <th
                        className="numeric"
                        title="Change in reported value, including price changes"
                      >
                        Value change
                      </th>
                      <th className="numeric">Holding value</th>
                      <th className="numeric">13F weight</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((change) => (
                      <tr
                        key={[
                          change.cusip,
                          change.security_class,
                          change.put_call,
                          change.share_type,
                        ].join("|")}
                      >
                        <td
                          title={`${change.security_class} · ${change.cusip}`}
                        >
                          {change.issuer}
                          {change.put_call && ` (${change.put_call})`}
                          <br />
                          <small>
                            {changeLabels[change.kind] ?? change.kind}
                          </small>
                          <br />
                          <small>
                            {quantity(change.previous_quantity)} →{" "}
                            {quantity(change.current_quantity)}{" "}
                            {change.share_type}
                          </small>
                        </td>
                        <td className="numeric">
                          <span
                            title={exactDollars(change.value_change_usd, true)}
                          >
                            {dollars(change.value_change_usd, true)}
                          </span>{" "}
                          <small title="Change in reported 13F portfolio weight, in percentage points">
                            ({weightChange(change.weight_change)})
                          </small>
                        </td>
                        <td className="numeric">
                          <span title={exactDollars(change.current_value_usd)}>
                            {dollars(change.current_value_usd)}
                          </span>
                        </td>
                        <td className="numeric">
                          {weight(change.current_weight)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        );
      })}
    </section>
  );
}

export function Research({
  section,
  anchor,
}: {
  section: "activity" | "managers" | "economics";
  anchor: string;
}) {
  return (
    <section
      id={anchor}
      aria-labelledby="research-heading"
      className={`research research-${section}`}
    >
      <h2 id="research-heading">
        <span aria-hidden="true">✳ </span>Research
      </h2>
      <nav
        className="research-links research-navigation"
        aria-label="Research navigation"
      >
        <a
          href="#research/activity"
          aria-current={section === "activity" ? "page" : undefined}
        >
          [ Stock activity ]
        </a>
        <a
          href="#research/managers"
          aria-current={section === "managers" ? "page" : undefined}
        >
          [ Managers ]
        </a>
        <a
          href="#research/economics"
          aria-current={section === "economics" ? "page" : undefined}
        >
          [ Economics ]
        </a>
      </nav>
      {section === "economics" ? (
        <Economics />
      ) : section === "activity" ? (
        <InstitutionalStockActivity />
      ) : (
        <ManagersDirectory />
      )}
    </section>
  );
}

function ManagersDirectory() {
  const [managers, setManagers] = useState<Manager[] | null>(null);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  const [search, setSearch] = useState("");
  const [verifiedOnly, setVerifiedOnly] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const detailRef = useRef<HTMLElement>(null);
  useEffect(() => {
    if (selected) {
      detailRef.current?.focus({ preventScroll: true });
      if (detailRef.current) detailRef.current.scrollTop = 0;
      if (window.matchMedia("(max-width: 800px)").matches) {
        detailRef.current?.scrollIntoView({ block: "start" });
      }
    }
  }, [selected]);
  useEffect(() => {
    let active = true;
    setError("");
    setManagers(null);
    api<{ managers: Manager[] }>("/research/managers").then(
      (data) => {
        if (active) setManagers(data.managers);
      },
      (failure) => {
        if (active) setError(errorMessage(failure));
      },
    );
    return () => {
      active = false;
    };
  }, [retry]);
  const visible = managers?.filter(
    (manager) =>
      (!verifiedOnly || manager.coverage.continuous_decade) &&
      [manager.name, manager.investor_names.join(" "), manager.focus]
        .join(" ")
        .toLowerCase()
        .includes(search.toLowerCase()),
  );
  return (
    <section aria-labelledby="managers-heading">
      <div className="directory-heading">
        <h3 id="managers-heading">Managers</h3>
        {managers && <span>{visible?.length} managers</span>}
      </div>
      {error && (
        <div className="error" role="alert">
          {error}
          <br />
          <button onClick={() => setRetry(retry + 1)}>Try again</button>
        </div>
      )}
      {!managers && !error && <p role="status">Loading managers…</p>}
      {managers && managers.length === 0 && (
        <p>No managers loaded yet. Load the research catalog to start.</p>
      )}
      {managers && managers.length > 0 && (
        <>
          <div className="research-controls">
            <label>
              Find a manager{" "}
              <input
                type="search"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
              />
            </label>
            <label>
              <input
                type="checkbox"
                checked={verifiedOnly}
                onChange={(event) => setVerifiedOnly(event.target.checked)}
              />{" "}
              Verified 10-year coverage only
            </label>
          </div>
          <div className="research-layout">
            <section
              className="research-directory"
              aria-label="Manager directory"
              tabIndex={0}
            >
              {visible?.length === 0 && <p>No managers match these filters.</p>}
              <ul className="manager-directory">
                {visible?.map((manager) => (
                  <li key={manager.slug}>
                    <button
                      className="manager-link"
                      onClick={() => setSelected(manager.slug)}
                      aria-pressed={selected === manager.slug}
                    >
                      {manager.name}
                    </button>
                    <p>{manager.investor_names.join(", ")}</p>
                    <p>{manager.focus}</p>
                    <AumSummary manager={manager} />
                    <p className="form-note">
                      {manager.history_start_year
                        ? `First observed filing period: ${manager.history_start_year}`
                        : "First filing period unverified"}
                      {" · "}
                      <span
                        title={
                          manager.portfolio_company_count_quarter
                            ? `Distinct stock issuers in ${quarterLabel(manager.portfolio_company_count_quarter)}; excludes options and principal positions`
                            : "Latest filing unavailable"
                        }
                      >
                        Portfolio companies:{" "}
                        {manager.portfolio_company_count ?? "Unavailable"}
                      </span>
                    </p>
                    <div className="research-links">
                      {manager.website_url && (
                        <SourceLink url={manager.website_url}>
                          Website
                        </SourceLink>
                      )}
                      {manager.letters_url && (
                        <SourceLink url={manager.letters_url}>
                          Letters & commentary
                        </SourceLink>
                      )}
                      <SourceLink
                        url={`https://www.sec.gov/edgar/browse/?CIK=${manager.cik}&owner=exclude`}
                      >
                        SEC filings
                      </SourceLink>
                    </div>
                  </li>
                ))}
              </ul>
            </section>
            <aside
              className="research-detail"
              aria-label="Manager research"
              ref={detailRef}
              tabIndex={-1}
            >
              {selected ? (
                <ManagerDetail key={selected} slug={selected} />
              ) : (
                <p>Select a manager to inspect quarterly position changes.</p>
              )}
            </aside>
          </div>
        </>
      )}
    </section>
  );
}

function ManagerDetail({ slug }: { slug: string }) {
  const [detail, setDetail] = useState<Detail | null>(null);
  const [quarter, setQuarter] = useState("");
  const [period, setPeriod] = useState("quarterly");
  const [year, setYear] = useState("");
  const [comparison, setComparison] = useState<Comparison | null>(null);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    let active = true;
    setError("");
    setDetail(null);
    setQuarter("");
    api<Detail>(`/research/managers/${slug}`).then(
      (data) => {
        if (active) {
          setDetail(data);
          setQuarter(data.filings[0]?.quarter ?? "");
          setYear(
            (current) => current || data.filings[0]?.quarter.slice(0, 4) || "",
          );
        }
      },
      (failure) => {
        if (active) setError(errorMessage(failure));
      },
    );
    return () => {
      active = false;
    };
  }, [slug, retry]);
  useEffect(() => {
    let active = true;
    setComparison(null);
    if (period === "annual" ? !year : !quarter) return;
    setError("");
    api<Comparison>(
      period === "annual"
        ? `/research/managers/${slug}/annual-changes?year=${year}`
        : `/research/managers/${slug}/changes?quarter=${quarter}`,
    ).then(
      (data) => {
        if (active) setComparison(data);
      },
      (failure) => {
        if (active) setError(errorMessage(failure));
      },
    );
    return () => {
      active = false;
    };
  }, [slug, quarter, period, year, retry]);
  return (
    <>
      {error && (
        <div className="error" role="alert">
          {error}
          <br />
          <button onClick={() => setRetry(retry + 1)}>Try again</button>
        </div>
      )}
      {!detail && !error && <p role="status">Loading filing history…</p>}
      {detail && (
        <>
          <h3>{detail.name}</h3>
          <p className="form-note">CIK {detail.cik}</p>
          <AumSummary manager={detail} />
          {detail.filings.length === 0 ? (
            <p>No quarterly holdings loaded yet.</p>
          ) : (
            <>
              <div className="research-controls">
                <label>
                  View{" "}
                  <select
                    aria-label="Comparison view"
                    value={period}
                    onChange={(event) => setPeriod(event.target.value)}
                  >
                    <option value="quarterly">Quarterly</option>
                    <option value="annual">Annual net change</option>
                  </select>
                </label>
                {period === "annual" ? (
                  <label>
                    Report year{" "}
                    <select
                      value={year}
                      onChange={(event) => setYear(event.target.value)}
                    >
                      {Array.from(
                        new Set(
                          detail.filings.map((filing) =>
                            filing.quarter.slice(0, 4),
                          ),
                        ),
                      ).map((value) => (
                        <option key={value} value={value}>
                          {value}
                        </option>
                      ))}
                    </select>
                  </label>
                ) : (
                  <label>
                    Report quarter{" "}
                    <select
                      value={quarter}
                      onChange={(event) => setQuarter(event.target.value)}
                    >
                      {Array.from(
                        new Set(detail.filings.map((filing) => filing.quarter)),
                      ).map((day) => (
                        <option key={day} value={day}>
                          {quarterLabel(day)}
                        </option>
                      ))}
                    </select>
                  </label>
                )}
              </div>
              {!comparison && !error && (
                <p role="status">Loading position changes…</p>
              )}
              {comparison?.status === "unavailable" && (
                <p role="status">Comparison unavailable: {comparison.reason}</p>
              )}
              {comparison?.status === "available" && (
                <>
                  {period === "annual" && (
                    <p>
                      {quarterLabel(comparison.previous_quarter)} →{" "}
                      {quarterLabel(comparison.quarter)}
                      {comparison.year_to_date && " · YTD"}
                    </p>
                  )}
                  {comparison.changes.length === 0 ? (
                    <p>No disclosed positions in these quarters.</p>
                  ) : (
                    <>
                      {period === "quarterly" && (
                        <ManagerWeightChart
                          key={`${comparison.previous_quarter}-${comparison.quarter}`}
                          comparison={comparison}
                        />
                      )}
                      <QuarterlyChanges
                        changes={comparison.changes}
                        annual={period === "annual"}
                      />
                    </>
                  )}
                </>
              )}
              {comparison && (
                <div className="research-links">
                  {comparison.source_urls.map((url, index) => (
                    <SourceLink key={url} url={url}>
                      Filing source {index + 1}
                    </SourceLink>
                  ))}
                </div>
              )}
            </>
          )}
          <details>
            <summary>Source notes</summary>
            {detail.notes && <p>{detail.notes}</p>}
            <p>
              {detail.history_start_year
                ? `History reference: ${detail.history_start_year}. Full quarterly coverage is checked separately.`
                : "Historical coverage awaits verification."}
            </p>
            {detail.history_source_url && (
              <p>
                <SourceLink url={detail.history_source_url}>
                  History reference
                </SourceLink>
              </p>
            )}
            {!detail.letters_url && <p>No public letter archive confirmed.</p>}
            <ul>
              {detail.source_urls.map((url, index) => (
                <li key={url}>
                  <SourceLink url={url}>Manager source {index + 1}</SourceLink>
                </li>
              ))}
            </ul>
          </details>
        </>
      )}
    </>
  );
}
