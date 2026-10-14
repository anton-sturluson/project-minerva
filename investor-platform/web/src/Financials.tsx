import { useEffect, useState } from "react";
import { annualFinancials } from "./financialApi";
import type { FinancialReport } from "./financialApi";
import { percent } from "./format";

const metrics = [
  ["gross_margin", "Gross margin"],
  ["operating_margin", "Operating margin"],
  ["net_margin_common", "Net margin (common shareholders)"],
  ["cfo_margin", "Consolidated CFO margin"],
  ["fcf_margin_after_disclosed_capex", "FCF margin after disclosed capex"],
] as const;

function missingReason(reason: string) {
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
        <strong>Illustrative weights — not your portfolio.</strong>
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
            <p className="form-note">
              Year-end weights: {report.holdings_date}. Financial periods end
              within {year}.
            </p>
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
                    const notes = [
                      ...new Set(
                        (metric?.contributions || [])
                          .flatMap((contribution) => [
                            contribution.calculation.review_note,
                          ])
                          .filter((note): note is string => Boolean(note)),
                      ),
                    ];
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
                          {sources.length > 0 || notes.length > 0 ? (
                            <details>
                              <summary>Source filings</summary>
                              {notes.map((note) => (
                                <p className="form-note" key={note}>
                                  {note}
                                </p>
                              ))}
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
            <p className="form-note">
              Each ratio uses covered equity value. Coverage measures all
              selected equity; cash is excluded. CFO is consolidated cash flow.
              Insurer cash flow may not be comparable to operating-company cash
              flow. FCF deducts separately disclosed capital spending;
              acquisition rows are excluded. These figures are not owner
              earnings.
            </p>
          </>
        ))}
    </section>
  );
}
