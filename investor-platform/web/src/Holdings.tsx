import { number, percent } from "./format";
import { exact, type Ledger } from "./records";
import type { Report } from "./Tracker";

export function Holdings({
  ledger,
  report,
}: {
  ledger: Ledger;
  report: Report | null;
}) {
  const rows = report
    ? [...report.holdings].sort((a, b) => Number(b.value) - Number(a.value))
    : ledger.holdings.map((h) => ({
        ticker: h.security.ticker,
        exchange: h.security.exchange,
        quantity: h.quantity,
        basis: h.cost_basis,
        close: null,
        value: null,
        weight: null,
        unrealized_pnl: null,
      }));
  const total = Number(report?.value ?? 0);
  const cash = report?.cash ?? ledger.balance;
  const top =
    report?.holdings
      .slice()
      .sort((a, b) => Number(b.value) - Number(a.value)) ?? [];
  const bars = top.slice(0, 5).map((h) => ({
    label: `${h.ticker} · ${h.exchange}`,
    value: Number(h.value),
  }));
  const other = top.slice(5).reduce((sum, h) => sum + Number(h.value), 0);
  if (other > 0) bars.push({ label: "Other holdings", value: other });
  if (Number(cash) > 0) bars.push({ label: "Cash", value: Number(cash) });
  return (
    <section
      aria-label="Portfolio holdings overview"
      className="holdings-overview"
    >
      <h2 id="holdings-heading">Holdings</h2>
      <p className="report-date">
        {report
          ? `${report.provisional ? "Provisional · " : ""}${report.end}`
          : "Recorded positions · market values unavailable"}
      </p>
      {report && total > 0 && (
        <figure
          className="allocation-chart"
          aria-label="Portfolio allocation by market value"
        >
          <figcaption>Top holdings · share of portfolio value</figcaption>
          {bars.map((bar) => (
            <div className="allocation-row" key={bar.label}>
              <span>{bar.label}</span>
              <span className="allocation-track" aria-hidden="true">
                <span
                  style={{
                    width: `${Math.max(0, Math.min(100, (bar.value / total) * 100))}%`,
                  }}
                />
              </span>
              <strong>{percent(String(bar.value / total))}</strong>
            </div>
          ))}
        </figure>
      )}
      <div className="table-scroll" tabIndex={0} aria-label="Holdings">
        <table>
          <thead>
            <tr>
              <th>Security</th>
              <th className="number">Shares</th>
              <th className="number">Close</th>
              <th className="number">Value ({ledger.currency})</th>
              <th className="number">Weight</th>
              <th className="number">Basis</th>
              <th className="number">Unrealized P&amp;L</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((h) => (
              <tr key={`${h.ticker}-${h.exchange}`}>
                <td>
                  {h.ticker} · {h.exchange}
                </td>
                <td className="number">{exact(h.quantity, 0)}</td>
                <td className="number">{number(h.close)}</td>
                <td className="number">{number(h.value)}</td>
                <td className="number">{percent(h.weight)}</td>
                <td className="number">{number(h.basis)}</td>
                <td className="number">{number(h.unrealized_pnl)}</td>
              </tr>
            ))}
            <tr>
              <td>Cash</td>
              <td>—</td>
              <td>—</td>
              <td className="number">{number(cash)}</td>
              <td className="number">
                {report && total > 0
                  ? percent(String(Number(cash) / total))
                  : "—"}
              </td>
              <td>—</td>
              <td>—</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  );
}
