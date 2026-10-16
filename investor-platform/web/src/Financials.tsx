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
  ["weighted_company_eps", "Weighted company EPS", 1],
  ["weighted_company_fcf_per_share", "Weighted company FCF/share", 1],
] as const;

function omissionReason(reason: string) {
  if (
    /revenue/i.test(reason) &&
    /zero|negative|nonpositive|non-positive/i.test(reason)
  )
    return /negative|nonpositive|non-positive/i.test(reason)
      ? "zero or negative revenue"
      : "no revenue";
  return /insurer/i.test(reason) && /not applicable/i.test(reason)
    ? "insurer"
    : "data unavailable";
}

export function Financials({
  accountId,
  year,
}: {
  accountId: string;
  year: number | null;
}) {
  const [retry, setRetry] = useState(0);
  const [report, setReport] = useState<FinancialReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(false);
    setReport(null);
    if (year === null) {
      setLoading(false);
      return;
    }
    annualFinancials(accountId, year)
      .then((data) => {
        if (!active) return;
        if (
          data.account_id !== accountId ||
          data.calendar_year !== year ||
          data.synthetic !== false
        )
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
  }, [accountId, year, retry]);
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
      ?.prior_year ?? (year === null ? null : year - 1);
  const footnotes = new Map(
    [
      ...rows
        .filter(
          ({ metric }) =>
            metric?.exclusions.length || metric?.conventions?.length,
        )
        .map(({ key }) => `${key}-exclusions`),
      ...rows
        .filter(({ metric }) => metric?.comparison?.exclusions?.length)
        .map(({ key }) => `${key}-prior-exclusions`),
    ].map((id, index) => [id, index + 1]),
  );
  return (
    <section
      className="annual-financials"
      aria-labelledby="financials-heading"
      aria-busy={loading}
    >
      <h2 id="financials-heading">Portfolio financials</h2>
      {year === null && (
        <p role="status">Choose a year to view portfolio financials.</p>
      )}
      {loading && <p role="status">Loading {year} financials…</p>}
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
          <p role="status">Table unavailable.</p>
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
                      {report.calendar_year}
                    </th>
                    <th scope="col" className="number">
                      {priorYear}
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
                          metric?.exclusions.length ||
                          metric?.conventions?.length
                            ? `${key}-exclusions`
                            : undefined
                        }
                      >
                        {label}
                        {Boolean(
                          metric?.exclusions.length ||
                          metric?.conventions?.length,
                        ) && <sup>{footnotes.get(`${key}-exclusions`)}</sup>}
                      </th>
                      <td className="number">
                        {metric?.value == null
                          ? "Unavailable"
                          : digits === null
                            ? percent(metric.value, 1)
                            : Number(metric.value).toLocaleString("en-US", {
                                style: "currency",
                                currency: "USD",
                                minimumFractionDigits: digits,
                                maximumFractionDigits: digits,
                              })}
                      </td>
                      <td
                        className="number"
                        aria-describedby={
                          metric?.comparison?.exclusions?.length
                            ? `${key}-prior-exclusions`
                            : undefined
                        }
                      >
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
                        {Boolean(metric?.comparison?.exclusions?.length) && (
                          <sup>{footnotes.get(`${key}-prior-exclusions`)}</sup>
                        )}
                      </td>
                      <td className="number">
                        {digits === null
                          ? "—"
                          : metric?.comparison?.status === "not_meaningful"
                            ? "N/M"
                            : metric?.comparison?.status === "calculated" &&
                                metric.comparison.percent_change != null
                              ? percent(metric.comparison.percent_change, 1)
                              : "Unavailable"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {rows
              .filter(
                ({ metric }) =>
                  metric?.exclusions.length || metric?.conventions?.length,
              )
              .map(({ key, label, metric }) => (
                <p className="form-note" id={`${key}-exclusions`} key={key}>
                  <sup>{footnotes.get(`${key}-exclusions`)}</sup> {label}
                  {metric!.exclusions.length ? " " : ": "}
                  {Boolean(metric!.exclusions.length) && (
                    <>
                      excludes{" "}
                      {metric!.exclusions
                        .map((excluded) => {
                          const company = report.companies.find(
                            (item) => item.issuer_key === excluded.issuer_key,
                          );
                          const name =
                            company?.ticker ||
                            tickers.get(excluded.issuer_key || "") ||
                            company?.name ||
                            "Company";
                          const why = omissionReason(excluded.reason);
                          return `${name} (${company?.equity_weight != null ? `${percent(company.equity_weight, 1)} weight` : "weight unavailable"}; ${why})`;
                        })
                        .join(", ")}
                      .
                    </>
                  )}
                  {Boolean(metric!.conventions?.length) && (
                    <>
                      {" "}
                      {metric!
                        .conventions!.map((item) => item.ticker || "Company")
                        .join(", ")}{" "}
                      included at 0% (no revenue).
                    </>
                  )}
                </p>
              ))}
            {rows
              .filter(({ metric }) => metric?.comparison?.exclusions?.length)
              .map(({ key, label, metric }) => (
                <p
                  className="form-note"
                  id={`${key}-prior-exclusions`}
                  key={`${key}-prior`}
                >
                  <sup>{footnotes.get(`${key}-prior-exclusions`)}</sup>{" "}
                  {priorYear} {label} excludes{" "}
                  {metric!
                    .comparison!.exclusions!.map(
                      (excluded) =>
                        `${excluded.ticker || "Company"} (${excluded.equity_weight != null ? `${percent(excluded.equity_weight, 1)} weight` : "weight unavailable"}; ${omissionReason(excluded.reason)})`,
                    )
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
                        {report.calendar_year}
                      </th>
                      <th scope="col" className="number">
                        {priorYear}
                      </th>
                      <th scope="col" className="number">
                        % change
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {report.companies.flatMap((company) => {
                      return [
                        { key: "basic_eps", label: "EPS (basic)", digits: 1 },
                        {
                          key: "fcf_per_basic_share",
                          label: "FCF/share",
                          digits: 1,
                        },
                      ].map((measure) => {
                        const comparison =
                          company.per_share_comparisons?.[measure.key];
                        const value = company.per_share_metrics?.[measure.key];
                        const available =
                          company.financial_status === "eligible" &&
                          value?.status === "available" &&
                          value.value != null;
                        return (
                          <tr key={`${company.issuer_key}:${measure.key}`}>
                            <th scope="row">
                              {company.ticker ||
                                tickers.get(company.issuer_key) ||
                                company.name ||
                                "Company"}
                            </th>
                            <td>
                              {measure.key === "basic_eps" &&
                              value?.eps_basis === "diluted"
                                ? "EPS (diluted)"
                                : measure.label}
                            </td>
                            <td className="number">
                              {available
                                ? Number(value?.value).toLocaleString("en-US", {
                                    style: "currency",
                                    currency: "USD",
                                    minimumFractionDigits: measure.digits,
                                    maximumFractionDigits: measure.digits,
                                  })
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
                                    ? percent(comparison.percent_change, 1)
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
