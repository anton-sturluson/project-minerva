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
  // Do not normalize a partial set of known bases into a misleading allocation.
  const completeBasis = rows.every((h) => h.basis !== null);
  const basisTotal = completeBasis
    ? rows.reduce((sum, h) => sum + Number(h.basis), Number(cash))
    : null;
  const costWeight = (basis: string | number | null) =>
    basis !== null && basisTotal !== null && basisTotal > 0
      ? String(Number(basis) / basisTotal)
      : null;
  const bars = rows.slice(0, 5).map((h) => ({
    label: h.ticker,
    exchange: h.exchange,
    value: Number(h.value),
    basis: h.basis === null ? null : Number(h.basis),
  }));
  const others = rows.slice(5);
  if (others.length)
    bars.push({
      label: "Other holdings",
      exchange: "",
      value: others.reduce((sum, h) => sum + Number(h.value), 0),
      basis: completeBasis
        ? others.reduce((sum, h) => sum + Number(h.basis), 0)
        : null,
    });
  if (Number(cash) > 0)
    bars.push({
      label: "Cash",
      exchange: "",
      value: Number(cash),
      basis: Number(cash),
    });
  return (
    <section
      aria-label="Portfolio holdings overview"
      className="holdings-overview"
    >
      <div className="section-heading">
        <h2 id="holdings-heading">Holdings</h2>
        <p className="report-date">
          {report
            ? `${report.provisional ? "Provisional · " : ""}${report.end}`
            : "Market values unavailable"}
        </p>
      </div>
      {report && total > 0 && (
        <figure
          className="allocation-chart"
          aria-label="Portfolio allocation by market value"
        >
          <figcaption>
            <span>
              Top holdings <small>· cash included</small>
            </span>
            <span className="allocation-legend">
              <span className="market-swatch" /> Market{" "}
              <span className="cost-swatch" /> Cost
            </span>
          </figcaption>
          <div className="allocation-columns" aria-hidden="true">
            <span />
            <span />
            <span>Market</span>
            <span>Cost</span>
          </div>
          {bars.map((bar) => {
            const market = bar.value / total;
            const cost = costWeight(bar.basis);
            return (
              <div
                className="allocation-row"
                key={`${bar.label}-${bar.exchange}`}
                aria-label={`${bar.label}${bar.exchange ? ` · ${bar.exchange}` : ""} allocation`}
              >
                <span className="allocation-name">
                  {bar.label}
                  <small>{bar.exchange}</small>
                </span>
                <span className="allocation-tracks" aria-hidden="true">
                  <span className="allocation-track">
                    <span
                      style={{
                        width: `${Math.max(0, Math.min(100, market * 100))}%`,
                      }}
                    />
                  </span>
                  <span className="allocation-track cost-track">
                    <span
                      style={{
                        width: `${Math.max(0, Math.min(100, Number(cost) * 100))}%`,
                      }}
                    />
                  </span>
                </span>
                <strong>{percent(String(market))}</strong>
                <span className="cost-weight">{percent(cost)}</span>
              </div>
            );
          })}
        </figure>
      )}
      {!completeBasis && (
        <p className="form-note basis-note">
          Cost weights unavailable · some positions have unknown basis.
        </p>
      )}
      <div className="table-scroll" tabIndex={0} aria-label="Holdings">
        <table className="holdings-table">
          <thead>
            <tr>
              <th scope="col">Security</th>
              <th scope="col" className="number">
                Shares
              </th>
              <th scope="col" className="number">
                Close
              </th>
              <th scope="col" className="number">
                Value ({ledger.currency})
              </th>
              <th scope="col" className="number">
                Market %
              </th>
              <th
                scope="col"
                className="number"
                title="Remaining cost basis / (total remaining basis + cash)"
              >
                Cost %
              </th>
              <th scope="col" className="number">
                Basis
              </th>
              <th scope="col" className="number">
                Unrealized P&amp;L
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((h) => (
              <tr key={`${h.ticker}-${h.exchange}`}>
                <th scope="row" className="security-name">
                  <strong>{h.ticker}</strong>
                  <small>{h.exchange}</small>
                </th>
                <td className="number">{exact(h.quantity, 0)}</td>
                <td className="number">{number(h.close)}</td>
                <td className="number">{number(h.value)}</td>
                <td className="number">{percent(h.weight)}</td>
                <td className="number cost-weight">
                  {percent(costWeight(h.basis))}
                </td>
                <td className="number">{number(h.basis)}</td>
                <td
                  className={`number ${h.unrealized_pnl === null || Number(h.unrealized_pnl) === 0 ? "" : Number(h.unrealized_pnl) > 0 ? "gain" : "loss"}`}
                >
                  {h.unrealized_pnl !== null && Number(h.unrealized_pnl) > 0
                    ? "+"
                    : ""}
                  {number(h.unrealized_pnl)}
                </td>
              </tr>
            ))}
            <tr className="cash-row">
              <th scope="row">Cash</th>
              <td>—</td>
              <td>—</td>
              <td className="number">{number(cash)}</td>
              <td className="number">
                {report && total > 0
                  ? percent(String(Number(cash) / total))
                  : "—"}
              </td>
              <td className="number cost-weight">
                {percent(costWeight(cash))}
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
