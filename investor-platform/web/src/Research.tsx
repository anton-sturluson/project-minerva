import { useEffect, useRef, useState } from "react";
import { api, errorMessage } from "./api";
import { StockActivity } from "./StockActivity";
import { percent, quarterLabel } from "./format";

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
  coverage: Coverage;
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
  current_weight: string | null;
};
type Comparison = {
  quarter: string;
  previous_quarter: string;
  status: "available" | "unavailable";
  reason: string | null;
  source_urls: string[];
  changes: Change[];
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
  return Number(value).toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
    signDisplay: signed ? "exceptZero" : "auto",
  });
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

function QuarterlyChanges({ changes }: { changes: Change[] }) {
  const groups = ["increased", "decreased", "unchanged"] as const;
  return (
    <section aria-label="Quarterly position changes">
      <p className="form-note">
        Largest absolute reported value changes first in each section. Value
        changes include price effects. Weights use the current reported 13F
        portfolio, not the whole fund.
      </p>
      {groups.map((group) => {
        const rows = changes.filter((change) => change.category === group);
        const label = group[0].toUpperCase() + group.slice(1);
        return (
          <section
            key={group}
            className="research-change-group"
            aria-label={`${label} positions`}
          >
            <h4>
              {label} <small>({rows.length})</small>
            </h4>
            {rows.length === 0 ? (
              <p className="form-note">No {group} positions.</p>
            ) : (
              <div className="table-scroll" tabIndex={0}>
                <table className="research-changes-table">
                  <thead>
                    <tr>
                      <th>Security</th>
                      <th className="numeric">Value change</th>
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
                        <td>
                          {change.issuer}
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
                          <br />
                          <small>
                            {change.security_class} {change.put_call} ·{" "}
                            {change.cusip}
                          </small>
                        </td>
                        <td className="numeric">
                          {dollars(change.value_change_usd, true)}
                        </td>
                        <td className="numeric">
                          {dollars(change.current_value_usd)}
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

export function Research({ activity }: { activity: boolean }) {
  return (
    <section
      id={activity ? "research/activity" : "research"}
      aria-labelledby="research-heading"
      className="research"
    >
      <h2 id="research-heading">
        <span aria-hidden="true">✳ </span>Research
      </h2>
      <nav
        className="research-links research-navigation"
        aria-label="Research navigation"
      >
        <a href="#research" aria-current={!activity ? "page" : undefined}>
          [ Managers ]
        </a>
        <a
          href="#research/activity"
          aria-current={activity ? "page" : undefined}
        >
          [ Stock activity ]
        </a>
      </nav>
      {activity ? <StockActivity /> : <ManagersDirectory />}
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
      detailRef.current?.scrollIntoView({ block: "start" });
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
        {managers && <span>{managers.length} managers</span>}
      </div>
      <p>Ideas from institutional holdings and investor letters.</p>
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
          <p className="form-note">
            Coverage is checked from loaded quarterly filings. A long history
            does not establish investment performance.
          </p>
          <div className="research-layout">
            <div>
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
                    <p className="form-note">
                      {manager.history_start_year
                        ? `First observed filing period: ${manager.history_start_year}`
                        : "First filing period unverified"}
                    </p>
                    <p className="form-note">
                      {manager.coverage.continuous_decade
                        ? "10-year coverage verified"
                        : manager.coverage.quarters > 0
                          ? `${manager.coverage.quarters} quarters loaded · 10-year coverage pending`
                          : "Filing history not loaded"}
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
            </div>
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
    if (!quarter) return;
    setError("");
    api<Comparison>(
      `/research/managers/${slug}/changes?quarter=${quarter}`,
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
  }, [slug, quarter, retry]);
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
          {detail.coverage.first_quarter && detail.coverage.last_quarter && (
            <p>
              {quarterLabel(detail.coverage.first_quarter)} –{" "}
              {quarterLabel(detail.coverage.last_quarter)} ·{" "}
              {detail.coverage.quarters} quarters loaded
            </p>
          )}
          {detail.filings.length === 0 ? (
            <p>No quarterly holdings loaded yet.</p>
          ) : (
            <>
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
              <p className="form-note">
                Reported position changes, inferred from quarter-end shares.
                These are not trade dates or prices. Splits and reporting
                changes can also change quantities.
              </p>
              {!comparison && !error && (
                <p role="status">Loading position changes…</p>
              )}
              {comparison?.status === "unavailable" && (
                <p role="status">Comparison unavailable: {comparison.reason}</p>
              )}
              {comparison?.status === "available" && (
                <>
                  <p>
                    Compared with {quarterLabel(comparison.previous_quarter)}
                  </p>
                  {comparison.changes.length === 0 ? (
                    <p>No disclosed positions in these quarters.</p>
                  ) : (
                    <QuarterlyChanges changes={comparison.changes} />
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
