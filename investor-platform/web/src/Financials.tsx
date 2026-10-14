import { useEffect, useState } from "react";
import { annualFinancials } from "./financialApi";
import type {
  FinancialCompany,
  FinancialMeasure,
  FinancialProfile,
  FinancialReport,
} from "./financialApi";
import { number, percent } from "./format";

const measures = [
  ["revenue", "Revenue", "fact", "dollars"],
  ["cost_of_revenue", "Cost of revenue", "fact", "dollars"],
  ["gross_profit", "Gross profit", "fact", "dollars"],
  ["operating_income", "Operating income", "fact", "dollars"],
  ["net_income_common", "Common earnings", "fact", "dollars"],
  ["operating_cash_flow", "Consolidated CFO", "fact", "dollars"],
  ["cash_capex_ppe", "Cash PP&E capex", "fact", "dollars"],
  ["fcf_after_ppe", "FCF after cash PP&E capex", "calculation", "dollars"],
  ["basic_eps", "Basic EPS", "fact", "per-share"],
  ["diluted_eps", "Diluted EPS", "fact", "per-share"],
  ["gross_margin", "Gross margin", "calculation", "percent"],
  ["operating_margin", "Operating margin", "calculation", "percent"],
  [
    "net_margin_common",
    "Common-shareholder net margin",
    "calculation",
    "percent",
  ],
  ["cfo_margin", "Consolidated CFO margin", "calculation", "percent"],
  [
    "fcf_margin_after_ppe",
    "FCF margin after cash PP&E capex",
    "calculation",
    "percent",
  ],
  [
    "allocated_cfo_per_basic_share",
    "Allocated CFO per basic share",
    "calculation",
    "per-share",
  ],
  [
    "allocated_fcf_after_ppe_per_basic_share",
    "Allocated FCF after PP&E per basic share",
    "calculation",
    "per-share",
  ],
] as const;

function reason(measure?: Pick<FinancialMeasure, "reason">) {
  const text = measure?.reason || "No compatible reported figure.";
  return text
    .replace("Missing/applicability inputs:", "Missing")
    .replaceAll("cash_capex_ppe", "cash PP&E spending")
    .replaceAll("basic_weighted_average_shares", "compatible basic shares")
    .replaceAll("net_income", "consolidated net income")
    .replaceAll("gross_profit", "gross profit")
    .replaceAll("cost_of_revenue", "cost of revenue")
    .replaceAll("operating_cash_flow", "operating cash flow")
    .split(". ")[0]
    .slice(0, 160);
}

function companyName(company: FinancialCompany, ticker?: string) {
  return company.profile
    ? `${company.profile.issuer.name}${ticker ? ` (${ticker})` : ""}`
    : ticker || "Company";
}

function Sources({
  profile,
  measure,
}: {
  profile: FinancialProfile;
  measure: FinancialMeasure;
}) {
  const ids = new Set([
    measure.source_id,
    ...(measure.inputs || []).map((input) => input.source_id),
  ]);
  const sources = profile.sources.filter((source) => ids.has(source.source_id));
  return (
    <>
      {sources.map((source, index) => (
        <span key={source.source_id}>
          {index > 0 && " · "}
          <a href={source.url} target="_blank" rel="noreferrer">
            Filing {source.published_on}
          </a>
        </span>
      ))}
    </>
  );
}

function CompanyFigures({
  company,
  ticker,
}: {
  company: FinancialCompany;
  ticker?: string;
}) {
  const profile = company.profile;
  return (
    <section
      className="financial-company"
      aria-label={companyName(company, ticker)}
    >
      <h3>{companyName(company, ticker)}</h3>
      {!profile || company.financial_status !== "eligible" ? (
        <p className="form-note">Annual figures aren't available yet.</p>
      ) : (
        <>
          <p className="form-note">
            {profile.period.fiscal_label} · {profile.period.start} through{" "}
            {profile.period.end} · USD
          </p>
          <div
            className="table-scroll"
            tabIndex={0}
            role="region"
            aria-label={`${profile.issuer.name} financial figures`}
          >
            <table className="financial-company-table">
              <thead>
                <tr>
                  <th scope="col">Measure</th>
                  <th scope="col" className="number">
                    Value
                  </th>
                  <th scope="col">Sources / missing data</th>
                </tr>
              </thead>
              <tbody>
                {measures.map(([key, label, kind, unit]) => {
                  const measure = (
                    kind === "fact" ? profile.facts : profile.calculations
                  )[key];
                  const available =
                    measure &&
                    ["reported", "calculated"].includes(measure.status) &&
                    measure.value != null;
                  const basis =
                    unit === "per-share"
                      ? measure?.share_basis ||
                        profile.facts.basic_weighted_average_shares?.share_basis
                      : undefined;
                  return (
                    <tr key={key}>
                      <th scope="row">
                        {label}
                        {basis && (
                          <small className="financial-share-basis">
                            {basis.classes
                              .map((name) =>
                                name.startsWith("class_")
                                  ? `Class ${name.slice(6).toUpperCase()}`
                                  : name.replaceAll("_", " "),
                              )
                              .join(" / ")}{" "}
                            · split basis through {basis.split_adjusted_through}
                            {basis.equivalence_note && (
                              <details>
                                <summary>Class equivalence</summary>
                                {basis.equivalence_note}
                              </details>
                            )}
                          </small>
                        )}
                      </th>
                      <td className="number">
                        {available
                          ? unit === "percent"
                            ? percent(measure.value!)
                            : number(measure.value!, unit === "dollars" ? 0 : 2)
                          : "Unavailable"}
                      </td>
                      <td>
                        {!available && (
                          <span className="financial-missing">
                            {reason(measure)}{" "}
                          </span>
                        )}
                        {measure && (
                          <Sources profile={profile} measure={measure} />
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}

export function Financials() {
  const [year, setYear] = useState(2025);
  const [retry, setRetry] = useState(0);
  const [report, setReport] = useState<FinancialReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(false);
    setReport(null);
    annualFinancials(year)
      .then((data) => {
        if (!active) return;
        if (data.calendar_year !== year || data.synthetic !== true)
          throw new Error("Unexpected report");
        setReport(data);
      })
      .catch(() => {
        if (active) setError(true);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [year, retry]);
  const tickers = Object.fromEntries(
    report?.market_value_snapshot.holdings.map((holding) => [
      holding.issuer_key,
      holding.ticker,
    ]) || [],
  );
  return (
    <section
      id="financials"
      aria-labelledby="financials-heading"
      aria-busy={loading}
    >
      <div className="section-heading">
        <h1 id="financials-heading">Annual financials</h1>
        <label>
          Fiscal year{" "}
          <select
            aria-label="Financial year"
            value={year}
            onChange={(event) => {
              setReport(null);
              setYear(Number(event.target.value));
            }}
          >
            {[2025, 2024, 2023].map((value) => (
              <option key={value} value={value}>
                FY{value}
              </option>
            ))}
          </select>
        </label>
      </div>
      <p className="financial-illustration">
        <strong>Illustrative weights — not your portfolio.</strong> Real company
        filings; example market-value weights.
      </p>
      {loading && <p role="status">Loading FY{year} financials…</p>}
      {error && (
        <p className="error" role="alert">
          Could not load annual figures.{" "}
          <button onClick={() => setRetry((value) => value + 1)}>
            Retry financials
          </button>
        </p>
      )}
      {!loading && !error && report && (
        <>
          <p className="financial-weights">
            {report.companies.map((company, index) => (
              <span key={company.issuer_key}>
                {index > 0 && " · "}
                {tickers[company.issuer_key] ||
                  company.profile?.issuer.name}:{" "}
                <strong>
                  {company.equity_weight === null
                    ? "Unavailable"
                    : percent(company.equity_weight, 0)}
                </strong>
              </span>
            ))}
          </p>
          <p className="form-note">
            Year-end weights: {report.holdings_date}. Financial periods end
            within {year}.
          </p>
          {report.api_status === "unavailable" || !report.companies.length ? (
            <p role="status">
              Annual figures aren't available yet.{" "}
              <button onClick={() => setRetry((value) => value + 1)}>
                Retry financials
              </button>
            </p>
          ) : (
            <>
              <h2>Weighted ratios</h2>
              <div
                className="table-scroll"
                tabIndex={0}
                role="region"
                aria-label="Weighted annual ratios"
              >
                <table className="financial-ratios-table">
                  <thead>
                    <tr>
                      <th scope="col">Measure</th>
                      <th scope="col" className="number">
                        Ratio
                      </th>
                      <th scope="col" className="number">
                        Coverage
                      </th>
                      <th scope="col">Missing data</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(report.weighted_ratios).map(
                      ([key, metric]) => (
                        <tr key={key}>
                          <th scope="row">{metric.label}</th>
                          <td className="number">
                            {metric.value == null
                              ? "Unavailable"
                              : percent(metric.value)}
                          </td>
                          <td className="number">
                            {metric.coverage === null
                              ? "Unavailable"
                              : percent(metric.coverage, 0)}
                          </td>
                          <td>
                            {metric.exclusions.length
                              ? metric.exclusions.map((excluded) => (
                                  <span
                                    className="financial-missing"
                                    key={excluded.issuer_key}
                                  >
                                    {tickers[excluded.issuer_key] || "Company"}:{" "}
                                    {reason({ reason: excluded.reason })}
                                  </span>
                                ))
                              : "—"}
                          </td>
                        </tr>
                      ),
                    )}
                  </tbody>
                </table>
              </div>
              <p className="form-note">
                Each ratio uses covered equity value. Coverage shows how much of
                the example is included; cash is excluded. Insurer cash flow may
                not be comparable to operating-company cash flow.
              </p>
              {report.companies.map((company) => (
                <CompanyFigures
                  key={company.issuer_key}
                  company={company}
                  ticker={tickers[company.issuer_key]}
                />
              ))}
              <p className="form-note">
                Cash flow per share allocates consolidated cash flow to basic
                shares. It is not owner earnings. FCF here subtracts cash PP&E
                capex only.
              </p>
            </>
          )}
        </>
      )}
    </section>
  );
}
