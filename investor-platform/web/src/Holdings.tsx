import { useCallback, useEffect, useState } from "react";
import { api, errorMessage } from "./api";
import { number as formatNumber, percent as formatPercent } from "./format";
import { type Ledger } from "./records";

const number = (value: string | null) => formatNumber(value, 1);
const percent = (value: string | null) => formatPercent(value, 1);
type Valuation = {
  end: string;
  provisional: boolean;
  value: string | null;
  cash: string;
  complete: boolean;
  holdings: {
    ticker: string;
    exchange: string;
    quantity: string;
    basis: string | null;
    close: string | null;
    value: string | null;
    weight: string | null;
    unrealized_pnl: string | null;
    price_error?: string | null;
    quote_date?: string | null;
  }[];
};

export function Holdings({
  ledger,
  accountId,
}: {
  ledger: Ledger;
  accountId: string;
}) {
  const [report, setReport] = useState<Valuation | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  const refresh = useCallback(() => setRevision((n) => n + 1), []);
  useEffect(() => {
    let active = true;
    setReport(null);
    setError("");
    setBusy(true);
    void api<Valuation>(`/accounts/${accountId}/valuation`, undefined, 60000)
      .then((value) => {
        if (active) setReport(value);
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
  }, [accountId, ledger, revision]);
  const rows = report
    ? [...report.holdings].sort(
        (a, b) => (Number(b.value) || 0) - (Number(a.value) || 0),
      )
    : ledger.holdings.map((h) => ({
        ticker: h.security.ticker,
        exchange: h.security.exchange,
        quantity: h.quantity,
        basis: h.cost_basis,
        close: null,
        value: null,
        weight: null,
        unrealized_pnl: null,
        price_error: null,
        quote_date: null,
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
  const stockBasis = completeBasis
    ? rows.reduce((sum, h) => sum + Number(h.basis), 0)
    : null;
  const stockValue = report?.complete
    ? rows.reduce((sum, h) => sum + Number(h.value), 0)
    : null;
  const stockGain =
    stockValue !== null && stockBasis !== null ? stockValue - stockBasis : null;
  const gainPercent = (
    gain: string | number | null,
    basis: string | number | null,
  ) =>
    gain !== null && basis !== null && Number(basis) > 0
      ? percent(String(Number(gain) / Number(basis)))
      : "—";
  const tone = (value: string | number | null) =>
    value === null || Number(value) === 0
      ? ""
      : Number(value) > 0
        ? "gain"
        : "loss";
  const signed = (value: string | number | null) =>
    (value !== null && Number(value) > 0 ? "+" : "") +
    number(value === null ? null : String(value));
  return (
    <section
      aria-label="Portfolio holdings overview"
      className="holdings-overview"
    >
      <div className="section-heading">
        <h2 id="holdings-heading">Holdings</h2>
        <button type="button" disabled={busy} onClick={refresh}>
          {busy ? "Updating…" : "Refresh prices"}
        </button>
      </div>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {report && !report.complete && (
        <p className="form-note basis-note">
          Missing prices · totals unavailable.
        </p>
      )}
      {!completeBasis && (
        <p className="form-note basis-note">
          Unknown basis · cost totals unavailable.
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
                Close (USD)
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
                Basis ({ledger.currency})
              </th>
              <th
                scope="col"
                className="number"
                title={`Unrealized gain or loss in ${ledger.currency} and as a percentage of remaining basis`}
              >
                Unrealized return ({ledger.currency} / %)
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((h) => (
              <tr key={`${h.ticker}-${h.exchange}`}>
                <th scope="row" className="security-name">
                  <strong>{h.ticker}</strong>
                  <small>{h.exchange}</small>
                  {h.price_error && (
                    <small className="loss">Quote unavailable</small>
                  )}
                </th>
                <td className="number" title={h.quantity}>
                  {number(h.quantity)}
                </td>
                <td
                  className="number"
                  title={
                    h.price_error ??
                    (h.quote_date ? `Close: ${h.quote_date}` : undefined)
                  }
                >
                  {number(h.close)}
                </td>
                <td className="number">{number(h.value)}</td>
                <td className="number">{percent(h.weight)}</td>
                <td className="number cost-weight">
                  {percent(costWeight(h.basis))}
                </td>
                <td className="number">{number(h.basis)}</td>
                <td className={`number ${tone(h.unrealized_pnl)}`}>
                  {signed(h.unrealized_pnl)}
                  {h.unrealized_pnl !== null && (
                    <> ({gainPercent(h.unrealized_pnl, h.basis)})</>
                  )}
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
          <tfoot>
            <tr>
              <th scope="row">Stocks total</th>
              <td>—</td>
              <td>—</td>
              <td className="number">
                {number(stockValue === null ? null : String(stockValue))}
              </td>
              <td className="number">
                {stockValue !== null && total > 0
                  ? percent(String(stockValue / total))
                  : "—"}
              </td>
              <td className="number cost-weight">
                {percent(costWeight(stockBasis))}
              </td>
              <td className="number">
                {number(stockBasis === null ? null : String(stockBasis))}
              </td>
              <td className={`number ${tone(stockGain)}`}>
                {signed(stockGain)}
                {stockGain !== null && (
                  <> ({gainPercent(stockGain, stockBasis)})</>
                )}
              </td>
            </tr>
          </tfoot>
        </table>
      </div>
    </section>
  );
}
