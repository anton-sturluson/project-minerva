import { useEffect, useState } from "react";
import { api, errorMessage, type Account } from "./api";
import { number, percent } from "./format";
import { today, type Ledger } from "./records";

type Stock = {
  security_id: string;
  ticker: string;
  exchange: string;
  contribution: string | null;
  gain: string;
};
type Attribution = {
  period: string;
  start: string;
  end: string;
  return: string | null;
  contribution_total: string | null;
  gain: string;
  stocks: Stock[];
};
const tone = (value: string | null) =>
  value === null || Number(value) === 0
    ? ""
    : Number(value) > 0
      ? "gain"
      : "loss";
const points = (value: string | null) =>
  value === null
    ? "—"
    : `${Number(value) > 0 ? "+" : ""}${number(String(Number(value) * 100))} pp`;

export function PostMortem({
  account,
  ledger,
}: {
  account: Account;
  ledger: Ledger;
}) {
  const [reports, setReports] = useState<Attribution[]>([]);
  const [selected, setSelected] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  const first = ledger.entries[0]?.effective_date;
  useEffect(() => {
    let active = true;
    setReports([]);
    setError("");
    setBusy(false);
    if (!first || account.base_currency !== "USD") return;
    const end = new Date(today() + "T12:00:00Z");
    end.setUTCDate(end.getUTCDate() - 1);
    setBusy(true);
    void api<{ attribution: Attribution[] | null }>(
      `/accounts/${account.id}/performance`,
      {
        method: "POST",
        body: JSON.stringify({
          start: first,
          end: end.toISOString().slice(0, 10),
          scope: "stocks",
        }),
      },
      60000,
    )
      .then((report) => {
        if (!active) return;
        const periods = report.attribution ?? [];
        setReports(periods);
        setSelected((current) =>
          periods.some((p) => p.period === current)
            ? current
            : (periods.at(-1)?.period ?? ""),
        );
      })
      .catch((e) => {
        if (active) setError(errorMessage(e));
      })
      .finally(() => {
        if (active) setBusy(false);
      });
    return () => {
      active = false;
    };
  }, [account.id, account.base_currency, first, ledger, revision]);
  const report = reports.find((p) => p.period === selected);
  const label = (p: Attribution) =>
    p.period === "all"
      ? "Full history"
      : `${p.period}${p.start.slice(0, 4) === p.period ? " · partial" : p.period === today().slice(0, 4) ? " · YTD" : ""}`;
  const leaders =
    report?.stocks.filter((s) => Number(s.contribution) > 0).slice(0, 3) ?? [];
  const detractors =
    report?.stocks
      .filter((s) => s.contribution !== null && Number(s.contribution) < 0)
      .slice(-3)
      .reverse() ?? [];
  return (
    <section
      className="post-mortem-content"
      aria-label="Stock contribution analysis"
    >
      {!first && <p>No stock history yet.</p>}
      {account.base_currency !== "USD" && (
        <p>Contributions currently support USD accounts only.</p>
      )}
      {busy && <p role="status">Calculating stock contributions…</p>}
      {error && (
        <p role="alert" className="error">
          {error}{" "}
          <button onClick={() => setRevision((n) => n + 1)}>
            Retry post-mortem
          </button>
        </p>
      )}
      {report && (
        <>
          <div className="post-mortem-period">
            <label>
              Year
              <select
                aria-label="Post-mortem year"
                value={selected}
                onChange={(e) => setSelected(e.target.value)}
              >
                {[...reports].reverse().map((p) => (
                  <option key={p.period} value={p.period}>
                    {label(p)}
                  </option>
                ))}
              </select>
            </label>
            <p>
              Stock portfolio return{" "}
              <strong className={tone(report.return)}>
                {percent(report.return)}
              </strong>
            </p>
          </div>
          <p className="form-note">
            Contribution to return · estimated · {report.start} — {report.end}
          </p>
          <div className="contribution-leaders">
            {[
              { title: "Main contributors", stocks: leaders },
              { title: "Main detractors", stocks: detractors },
            ].map((group) => (
              <section key={group.title} aria-label={group.title}>
                <h3>{group.title}</h3>
                {group.stocks.length ? (
                  <ol>
                    {group.stocks.map((stock) => (
                      <li key={stock.security_id}>
                        <span>
                          {stock.ticker} <small>{stock.exchange}</small>
                        </span>
                        <strong className={tone(stock.contribution)}>
                          {points(stock.contribution)}
                        </strong>
                      </li>
                    ))}
                  </ol>
                ) : (
                  <p className="form-note">
                    {report.return === null
                      ? "Unavailable for this period."
                      : "None this period."}
                  </p>
                )}
              </section>
            ))}
          </div>
          <div
            className="table-scroll"
            tabIndex={0}
            aria-label="Stock contributions"
          >
            <table>
              <thead>
                <tr>
                  <th scope="col">Stock</th>
                  <th
                    scope="col"
                    className="number"
                    title="Linked percentage-point contribution to portfolio return"
                  >
                    Contribution (pp)
                  </th>
                  <th
                    scope="col"
                    className="number"
                    title="Realized and unrealized price changes plus estimated gross dividends, after recorded trading costs"
                  >
                    Investment gain (USD)
                  </th>
                </tr>
              </thead>
              <tbody>
                {report.stocks.map((stock) => (
                  <tr key={stock.security_id}>
                    <th scope="row">
                      {stock.ticker} <small>{stock.exchange}</small>
                    </th>
                    <td className={`number ${tone(stock.contribution)}`}>
                      {points(stock.contribution)}
                    </td>
                    <td className={`number ${tone(stock.gain)}`}>
                      {Number(stock.gain) > 0 ? "+" : ""}
                      {number(stock.gain, 1)}
                    </td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr>
                  <th
                    scope="row"
                    title="Unrounded contributions sum to the displayed portfolio return"
                  >
                    Total
                  </th>
                  <td className={`number ${tone(report.contribution_total)}`}>
                    {points(report.contribution_total)}
                  </td>
                  <td className={`number ${tone(report.gain)}`}>
                    {Number(report.gain) > 0 ? "+" : ""}
                    {number(report.gain, 1)}
                  </td>
                </tr>
              </tfoot>
            </table>
          </div>
        </>
      )}
      {!busy &&
        !error &&
        first &&
        account.base_currency === "USD" &&
        !report && <p>No stock contribution history.</p>}
    </section>
  );
}
