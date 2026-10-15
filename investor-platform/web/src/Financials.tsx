import { useEffect, useState } from "react";
import { annualFinancials } from "./financialApi";
import type { FinancialReport } from "./financialApi";
import { percent } from "./format";

const metrics = [
  ["gross_margin", "Gross margin"],
  ["operating_margin", "Operating margin"],
  ["fcf_margin_after_disclosed_capex", "FCF margin"],
] as const;
const perShareMetrics = [
  ["weighted_company_eps", "Weighted company EPS", 2],
  ["weighted_company_fcf_per_share", "Weighted company FCF/share", 4],
] as const;

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
  const tickers = new Map(
    report?.market_value_snapshot?.holdings.map((holding) => [
      holding.issuer_key,
      holding.ticker,
    ]) || [],
  );
  const rows = [
    ...metrics.map(([key, label]) => ({
      key,
      label,
      metric: report?.weighted_ratios[key],
      digits: null,
    })),
    ...perShareMetrics.map(([key, label, digits]) => ({
      key,
      label,
      metric: report?.weighted_company_per_share?.[key],
      digits,
    })),
  ];
  const priorYear =
    report?.weighted_company_per_share?.weighted_company_eps?.comparison
      ?.prior_year ?? year - 1;
  return (
    <section
      className="annual-financials"
      aria-labelledby="financials-heading"
      aria-busy={loading}
    >
      <div className="section-heading">
        <h2 id="financials-heading">Annual financials</h2>
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
        <strong>Illustrative weights</strong>
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
      {!loading &&
        !error &&
        report &&
        (report.api_status === "unavailable" ? (
          <p role="status">
            Annual figures aren't available yet.{" "}
            <button onClick={() => setRetry((value) => value + 1)}>
              Retry financials
            </button>
          </p>
        ) : (
          <>
            <div
              className="table-scroll"
              tabIndex={0}
              role="region"
              aria-label="Portfolio-weighted metrics"
            >
              <table className="financial-ratios-table">
                <thead>
                  <tr>
                    <th scope="col">Measure</th>
                    <th scope="col" className="number">
                      FY{report.calendar_year}
                    </th>
                    <th scope="col" className="number">
                      FY{priorYear}
                    </th>
                    <th scope="col" className="number">
                      % change
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map(({ key, label, metric, digits }) => (
                    <tr key={key}>
                      <th
                        scope="row"
                        aria-describedby={
                          metric?.exclusions.length
                            ? `${key}-exclusions`
                            : undefined
                        }
                      >
                        {label}
                        {Boolean(metric?.exclusions.length) && <sup>*</sup>}
                      </th>
                      <td className="number">
                        {metric?.value == null
                          ? "Unavailable"
                          : digits === null
                            ? percent(metric.value)
                            : Number(metric.value).toLocaleString("en-US", {
                                style: "currency",
                                currency: "USD",
                                minimumFractionDigits: digits,
                                maximumFractionDigits: digits,
                              })}
                      </td>
                      <td className="number">
                        {digits === null
                          ? "—"
                          : metric?.comparison?.prior_value == null
                            ? "Unavailable"
                            : Number(
                                metric.comparison.prior_value,
                              ).toLocaleString("en-US", {
                                style: "currency",
                                currency: "USD",
                                minimumFractionDigits: digits,
                                maximumFractionDigits: digits,
                              })}
                      </td>
                      <td className="number">
                        {digits === null
                          ? "—"
                          : metric?.comparison?.status === "not_meaningful"
                            ? "N/M"
                            : metric?.comparison?.status === "calculated" &&
                                metric.comparison.percent_change != null
                              ? percent(metric.comparison.percent_change)
                              : "Unavailable"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {rows
              .filter(({ metric }) => metric?.exclusions.length)
              .map(({ key, label, metric }) => (
                <p className="form-note" id={`${key}-exclusions`} key={key}>
                  * {label} excludes{" "}
                  {metric!.exclusions
                    .map((excluded) => {
                      const company = report.companies.find(
                        (item) => item.issuer_key === excluded.issuer_key,
                      );
                      const name =
                        tickers.get(excluded.issuer_key || "") ||
                        company?.profile?.issuer?.name ||
                        "Company";
                      const why =
                        /insurer/i.test(excluded.reason) &&
                        /not applicable/i.test(excluded.reason)
                          ? "insurer"
                          : "data unavailable";
                      return `${name} (${company?.equity_weight != null ? `${percent(company.equity_weight, 0)} weight` : "weight unavailable"}; ${why})`;
                    })
                    .join(", ")}
                  .
                </p>
              ))}
            <details>
              <summary>Company details</summary>
              <div
                className="table-scroll"
                tabIndex={0}
                role="region"
                aria-label="Company per-share figures"
              >
                <table className="financial-per-share-table">
                  <thead>
                    <tr>
                      <th scope="col">Company</th>
                      <th scope="col">Measure</th>
                      <th scope="col" className="number">
                        FY{report.calendar_year}
                      </th>
                      <th scope="col" className="number">
                        FY{priorYear}
                      </th>
                      <th scope="col" className="number">
                        % change
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {report.companies.flatMap((company) => {
                      const profile = company.profile;
                      const reviewed =
                        company.financial_status === "eligible" &&
                        profile?.review_status === "reviewed";
                      return [
                        {
                          key: "basic_eps",
                          label: "EPS (basic)",
                          value: profile?.facts?.basic_eps,
                          status: "reported",
                          digits: 2,
                        },
                        {
                          key: "allocated_fcf_after_disclosed_capex_per_basic_share",
                          label: "FCF/share",
                          value:
                            profile?.calculations
                              ?.allocated_fcf_after_disclosed_capex_per_basic_share,
                          status: "calculated",
                          digits: 4,
                        },
                      ].map((measure) => {
                        const comparison =
                          company.per_share_comparisons?.[measure.key];
                        const available =
                          reviewed &&
                          measure.value?.status === measure.status &&
                          measure.value.value != null;
                        return (
                          <tr key={`${company.issuer_key}:${measure.key}`}>
                            <th scope="row">
                              {tickers.get(company.issuer_key) ||
                                profile?.issuer?.name ||
                                "Company"}
                            </th>
                            <td>{measure.label}</td>
                            <td className="number">
                              {available
                                ? Number(measure.value?.value).toLocaleString(
                                    "en-US",
                                    {
                                      style: "currency",
                                      currency: "USD",
                                      minimumFractionDigits: measure.digits,
                                      maximumFractionDigits: measure.digits,
                                    },
                                  )
                                : "Unavailable"}
                            </td>
                            <td className="number">
                              {comparison?.prior_value != null
                                ? Number(comparison.prior_value).toLocaleString(
                                    "en-US",
                                    {
                                      style: "currency",
                                      currency: "USD",
                                      minimumFractionDigits: measure.digits,
                                      maximumFractionDigits: measure.digits,
                                    },
                                  )
                                : "Unavailable"}
                            </td>
                            <td className="number">
                              {!available
                                ? "Unavailable"
                                : comparison?.status === "not_meaningful"
                                  ? "N/M"
                                  : comparison?.status === "calculated" &&
                                      comparison.percent_change != null
                                    ? percent(comparison.percent_change)
                                    : "Unavailable"}
                            </td>
                          </tr>
                        );
                      });
                    })}
                  </tbody>
                </table>
              </div>
            </details>
          </>
        ))}
    </section>
  );
}
