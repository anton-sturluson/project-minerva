import { useEffect, useState } from "react";
import { annualFinancials } from "./financialApi";
import type {
  FinancialBasisNote,
  FinancialComparison,
  FinancialExclusion,
  FinancialReport,
} from "./financialApi";
import { percent } from "../format";

const metrics = [
  ["gross_margin", "Gross margin"],
  ["operating_margin", "Operating margin"],
  ["fcf_margin_after_disclosed_capex", "FCF margin"],
] as const;
const perShareMetrics = [
  ["weighted_company_eps", "Weighted company EPS"],
  ["weighted_company_fcf_per_share", "Weighted company FCF/share"],
] as const;

function isNotReported(reason?: string | null) {
  return /^(EPS|Gross margin|Operating margin) not reported:/.test(
    reason || "",
  );
}

function omissionReason(reason: string) {
  if (isNotReported(reason)) return "not reported";
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

type AmountFormat = "percent" | "currency";
type FinancialNote = {
  id: string;
  label: string;
  exclusions: FinancialExclusion[];
  basisNotes: FinancialBasisNote[];
};

function amount(value: string | null | undefined, format: AmountFormat) {
  if (value == null) return "Unavailable";
  return format === "percent"
    ? percent(value, 1)
    : Number(value).toLocaleString("en-US", {
        style: "currency",
        currency: "USD",
        minimumFractionDigits: 1,
        maximumFractionDigits: 1,
      });
}

function change(comparison?: FinancialComparison) {
  if (comparison?.status === "not_meaningful") return "N/M";
  return comparison?.status === "calculated" &&
    comparison.percent_change != null
    ? percent(comparison.percent_change, 1)
    : "Unavailable";
}

function FinancialNote({
  note,
  number,
}: {
  note: FinancialNote;
  number: number;
}) {
  const exclusions = note.exclusions
    .map(
      (excluded) =>
        `${excluded.ticker} (${excluded.equity_weight != null ? `${percent(excluded.equity_weight, 1)} weight` : "weight unavailable"}; ${omissionReason(excluded.reason)})`,
    )
    .join(", ");
  const basis = note.basisNotes
    .map((item) => `${item.ticker}: ${item.note}`)
    .join("; ");
  return (
    <p className="form-note" id={note.id}>
      <sup>{number}</sup> {note.label}
      {exclusions ? ` excludes ${exclusions}.` : ": "}
      {basis ? `${exclusions ? " " : ""}${basis}.` : null}
    </p>
  );
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
  const rows = [
    ...metrics.map(([key, label]) => ({
      key,
      label,
      metric: report?.weighted_ratios[key],
      format: "percent" as const,
    })),
    ...perShareMetrics.map(([key, label]) => ({
      key,
      label,
      metric: report?.weighted_company_per_share?.[key],
      format: "currency" as const,
    })),
  ];
  const priorYear =
    report?.weighted_company_per_share?.weighted_company_eps?.comparison
      ?.prior_year ?? (year === null ? null : year - 1);
  const notes: FinancialNote[] = [
    ...rows.map(({ key, label, metric }) => ({
      id: `${key}-exclusions`,
      label,
      exclusions: metric?.exclusions ?? [],
      basisNotes: metric?.basis_notes ?? [],
    })),
    ...rows.map(({ key, label, metric }) => ({
      id: `${key}-prior-exclusions`,
      label: `${priorYear} ${label}`,
      exclusions: metric?.comparison?.exclusions ?? [],
      basisNotes: metric?.comparison?.basis_notes ?? [],
    })),
  ].filter((note) => note.exclusions.length || note.basisNotes.length);
  const footnotes = new Map(notes.map((note, index) => [note.id, index + 1]));
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
            <p className="form-note">
              Holdings as of {report.holdings_date}. Annual financial periods
              ending in {report.calendar_year}. Retrospective figures;
              publication dates are not limited to the holdings date.
            </p>
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
                  {rows.map(({ key, label, metric, format }) => (
                    <tr key={key}>
                      <th scope="row">{label}</th>
                      <td
                        className="number"
                        aria-describedby={
                          footnotes.has(`${key}-exclusions`)
                            ? `${key}-exclusions`
                            : undefined
                        }
                      >
                        {amount(metric?.value, format)}
                        {footnotes.has(`${key}-exclusions`) && (
                          <sup>{footnotes.get(`${key}-exclusions`)}</sup>
                        )}
                      </td>
                      <td
                        className="number"
                        aria-describedby={
                          footnotes.has(`${key}-prior-exclusions`)
                            ? `${key}-prior-exclusions`
                            : undefined
                        }
                      >
                        {amount(metric?.comparison?.prior_value, format)}
                        {footnotes.has(`${key}-prior-exclusions`) && (
                          <sup>{footnotes.get(`${key}-prior-exclusions`)}</sup>
                        )}
                      </td>
                      <td className="number">{change(metric?.comparison)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {notes.map((note, index) => (
              <FinancialNote key={note.id} note={note} number={index + 1} />
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
                        { key: "basic_eps", label: "EPS (basic)" },
                        {
                          key: "fcf_per_basic_share",
                          label: "FCF/share",
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
                          <tr
                            key={`${company.issuer_key}:${company.exchange}:${company.ticker}:${measure.key}`}
                          >
                            <th scope="row">
                              {company.ticker || company.name || "Company"}
                            </th>
                            <td>
                              {measure.key === "basic_eps" &&
                              value?.eps_basis === "diluted"
                                ? "EPS (diluted)"
                                : measure.key === "fcf_per_basic_share" &&
                                    value?.share_denominator_basis ===
                                      "diluted_weighted_average"
                                  ? "FCF/share (diluted shares)"
                                  : measure.label}
                            </td>
                            <td className="number">
                              {available
                                ? amount(value?.value, "currency")
                                : isNotReported(value?.reason)
                                  ? "Not reported"
                                  : "Unavailable"}
                            </td>
                            <td className="number">
                              {comparison?.prior_value != null
                                ? amount(comparison.prior_value, "currency")
                                : isNotReported(comparison?.reason)
                                  ? "Not reported"
                                  : "Unavailable"}
                            </td>
                            <td className="number">
                              {available ? change(comparison) : "Unavailable"}
                            </td>
                          </tr>
                        );
                      });
                    })}
                  </tbody>
                </table>
              </div>
              <section aria-label="Financial sources and periods">
                <h3>Sources and periods</h3>
                {report.publication_policy && (
                  <p className="form-note">{report.publication_policy}</p>
                )}
                <ul>
                  {report.companies.map((company) => (
                    <li
                      key={`${company.issuer_key}:${company.exchange}:${company.ticker}`}
                    >
                      <strong>
                        {company.ticker || company.name || company.issuer_key}
                      </strong>
                      {company.period && (
                        <p>
                          Current period: {company.period.start} through{" "}
                          {company.period.end}
                          {company.period.fiscal_label
                            ? ` (${company.period.fiscal_label})`
                            : ""}
                          .
                        </p>
                      )}
                      {company.prior_period && (
                        <p>
                          Prior period: {company.prior_period.start} through{" "}
                          {company.prior_period.end}
                          {company.prior_period.fiscal_label
                            ? ` (${company.prior_period.fiscal_label})`
                            : ""}
                          .
                        </p>
                      )}
                      {company.source_urls?.length ? (
                        <ul>
                          {company.source_urls.map((url, index) => (
                            <li key={url}>
                              <a href={url} target="_blank" rel="noreferrer">
                                {company.ticker || company.name || "Company"}{" "}
                                filing source {index + 1}
                              </a>
                            </li>
                          ))}
                        </ul>
                      ) : (
                        <p className="form-note">
                          No linked filing source available.
                        </p>
                      )}
                    </li>
                  ))}
                </ul>
              </section>
            </details>
          </>
        ))}
    </section>
  );
}
