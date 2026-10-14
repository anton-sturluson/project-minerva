import { useEffect, useState } from "react";
import { annualFinancials } from "./financialApi";
import type { FinancialReport } from "./financialApi";
import { percent } from "./format";

const metrics = [
  ["gross_margin", "Gross margin"],
  ["operating_margin", "Operating margin"],
  ["fcf_margin_after_disclosed_capex", "FCF margin"],
] as const;

function missingReason(reason: string) {
  if (/insurer/i.test(reason) && /not applicable/i.test(reason))
    return "Not applicable to insurers";
  return reason
    .replace("Missing/applicability inputs:", "Missing")
    .replaceAll("cash_capex_ppe", "cash PP&E spending")
    .replaceAll("net_income", "consolidated net income")
    .replaceAll("gross_profit", "gross profit")
    .replaceAll("cost_of_revenue", "cost of revenue")
    .replaceAll("operating_cash_flow", "operating cash flow")
    .split(". ")[0]
    .slice(0, 160);
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
        if (data.calendar_year !== year || data.synthetic !== true) {
          throw new Error("Unexpected report");
        }
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
                    <th scope="col">Sources</th>
                  </tr>
                </thead>
                <tbody>
                  {metrics.map(([key, label]) => {
                    const metric = report.weighted_ratios[key];
                    const sources = [
                      ...new Map(
                        (metric?.contributions || [])
                          .flatMap((contribution) => {
                            const ids = new Set(
                              contribution.calculation.inputs.map(
                                (input) => input.source_id,
                              ),
                            );
                            return (
                              report.companies
                                .find(
                                  (company) =>
                                    company.issuer_key ===
                                    contribution.issuer_key,
                                )
                                ?.profile?.sources.filter((source) =>
                                  ids.has(source.source_id),
                                ) || []
                            );
                          })
                          .map((source) => [source.url, source]),
                      ).values(),
                    ];
                    return (
                      <tr key={key}>
                        <th scope="row">{label}</th>
                        <td className="number">
                          {metric?.value == null
                            ? "Unavailable"
                            : percent(metric.value)}
                        </td>
                        <td className="number">
                          {metric?.coverage == null
                            ? "Unavailable"
                            : percent(metric.coverage, 0)}
                        </td>
                        <td>
                          {metric?.exclusions.length
                            ? [
                                ...new Set(
                                  metric.exclusions.map((excluded) =>
                                    missingReason(excluded.reason),
                                  ),
                                ),
                              ].map((reason) => (
                                <span
                                  className="financial-missing"
                                  key={reason}
                                >
                                  {reason}
                                </span>
                              ))
                            : metric
                              ? "—"
                              : "Annual measure not available"}
                        </td>
                        <td>
                          {sources.length > 0 ? (
                            <details>
                              <summary>Source filings</summary>
                              <ul>
                                {sources.map((source) => (
                                  <li key={source.url}>
                                    <a
                                      href={source.url}
                                      target="_blank"
                                      rel="noreferrer"
                                    >
                                      Filing {source.published_on}
                                    </a>
                                  </li>
                                ))}
                              </ul>
                            </details>
                          ) : (
                            "—"
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
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
                    <th scope="col" className="number">
                      EPS (basic)
                    </th>
                    <th scope="col" className="number">
                      FCF/share
                    </th>
                    <th scope="col">Sources</th>
                  </tr>
                </thead>
                <tbody>
                  {report.companies.map((company) => {
                    const profile = company.profile;
                    const reviewed =
                      company.financial_status === "eligible" &&
                      profile?.review_status === "reviewed";
                    const eps = profile?.facts?.basic_eps;
                    const fcf =
                      profile?.calculations
                        ?.allocated_fcf_after_disclosed_capex_per_basic_share;
                    const sourceIds = new Set([
                      eps?.source_id,
                      ...(fcf?.inputs || []).map((input) => input.source_id),
                    ]);
                    const sources = reviewed
                      ? profile.sources.filter((source) =>
                          sourceIds.has(source.source_id),
                        )
                      : [];
                    const ticker = tickers.get(company.issuer_key);
                    return (
                      <tr key={company.issuer_key}>
                        <th scope="row">
                          {ticker || profile?.issuer?.name || "Company"}
                        </th>
                        <td className="number">
                          {reviewed &&
                          eps?.status === "reported" &&
                          eps.value != null
                            ? Number(eps.value).toLocaleString("en-US", {
                                style: "currency",
                                currency: "USD",
                                minimumFractionDigits: 2,
                                maximumFractionDigits: 2,
                              })
                            : "Unavailable"}
                        </td>
                        <td className="number">
                          {reviewed &&
                          fcf?.status === "calculated" &&
                          fcf.value != null
                            ? Number(fcf.value).toLocaleString("en-US", {
                                style: "currency",
                                currency: "USD",
                                minimumFractionDigits: 4,
                                maximumFractionDigits: 4,
                              })
                            : "Unavailable"}
                        </td>
                        <td>
                          {sources.length > 0 ? (
                            <details>
                              <summary>Source filings</summary>
                              <ul>
                                {sources.map((source) => (
                                  <li key={source.url}>
                                    <a
                                      href={source.url}
                                      target="_blank"
                                      rel="noreferrer"
                                    >
                                      Filing {source.published_on}
                                    </a>
                                  </li>
                                ))}
                              </ul>
                            </details>
                          ) : (
                            "—"
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </>
        ))}
    </section>
  );
}
