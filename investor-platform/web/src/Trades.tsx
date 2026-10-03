import { useRef, useState, type FormEvent } from "react";
import { api, errorMessage, type Account } from "./api";
import { exact, today, type Entry, type Holding } from "./records";

export function Trades({
  account,
  holdings,
  onSaved,
}: {
  account: Account;
  holdings: Holding[];
  onSaved: () => Promise<void>;
}) {
  const [kind, setKind] = useState("buy");
  const [ticker, setTicker] = useState("");
  const [exchange, setExchange] = useState("");
  const [date, setDate] = useState(today());
  const [quantity, setQuantity] = useState("");
  const [price, setPrice] = useState("");
  const [fees, setFees] = useState("0");
  const [basis, setBasis] = useState("");
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const retry = useRef<{ body: string; key: string } | null>(null);
  async function save(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError("");
    setMessage("");
    const payload = {
      kind,
      ticker,
      exchange,
      currency: account.base_currency,
      effective_date: date,
      quantity,
      price: kind === "opening_position" ? null : price,
      fees: kind === "opening_position" ? "0" : fees,
      cost_basis: kind === "opening_position" && basis !== "" ? basis : null,
      note,
    };
    const body = JSON.stringify(payload);
    if (retry.current?.body !== body)
      retry.current = { body, key: crypto.randomUUID() };
    try {
      await api<Entry>(`/accounts/${account.id}/trades`, {
        method: "POST",
        body: JSON.stringify({ ...payload, request_key: retry.current.key }),
      });
      retry.current = null;
      setQuantity("");
      setNote("");
      setMessage("Position entry saved.");
      await onSaved();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setSaving(false);
    }
  }
  return (
    <section className="positions" aria-labelledby="holdings-heading">
      <h3 id="holdings-heading">Holdings</h3>
      <p className="form-note">
        Long-only equities in {account.base_currency}. Cost basis is not market
        value. No live prices.
      </p>
      {holdings.length ? (
        <div className="table-scroll" tabIndex={0} aria-label="Holdings">
          <table>
            <thead>
              <tr>
                <th>Security</th>
                <th>Exchange</th>
                <th className="number">Shares</th>
                <th className="number">
                  Remaining basis ({account.base_currency})
                </th>
              </tr>
            </thead>
            <tbody>
              {holdings.map((h) => (
                <tr key={h.security.id}>
                  <td>{h.security.ticker}</td>
                  <td>{h.security.exchange}</td>
                  <td className="number">{exact(h.quantity, 0)}</td>
                  <td className="number">
                    {h.cost_basis === null ? "Unknown" : exact(h.cost_basis)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p>No open positions.</p>
      )}
      <details className="entry-panel">
        <summary>Record a position or trade</summary>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        {message && (
          <p className="save-message" aria-live="polite">
            {message}
          </p>
        )}
        <form className="entry-form" onSubmit={(e) => void save(e)}>
          <label>
            Action
            <select
              aria-label="Position action"
              value={kind}
              disabled={saving}
              onChange={(e) => setKind(e.target.value)}
            >
              <option value="opening_position">Opening position</option>
              <option value="buy">Buy</option>
              <option value="sell">Sell</option>
            </select>
          </label>
          <label>
            Ticker
            <input
              aria-label="Ticker"
              required
              maxLength={20}
              pattern="[A-Z0-9][A-Z0-9.\-]{0,19}"
              value={ticker}
              onChange={(e) => setTicker(e.target.value.toUpperCase())}
              disabled={saving}
            />
          </label>
          <label>
            Exchange
            <input
              aria-label="Exchange"
              required
              maxLength={12}
              pattern="[A-Z0-9][A-Z0-9_\-]{1,11}"
              placeholder="e.g. NASDAQ"
              value={exchange}
              onChange={(e) => setExchange(e.target.value.toUpperCase())}
              disabled={saving}
            />
          </label>
          <label>
            Effective date (UTC)
            <input
              aria-label="Position effective date"
              type="date"
              required
              max={today()}
              value={date}
              onChange={(e) => setDate(e.target.value)}
              disabled={saving}
            />
          </label>
          <label>
            Shares
            <input
              aria-label="Shares"
              type="number"
              required
              min="0.00000001"
              step="0.00000001"
              value={quantity}
              onChange={(e) => setQuantity(e.target.value)}
              disabled={saving}
            />
          </label>
          {kind === "opening_position" ? (
            <label>
              Total cost basis ({account.base_currency}, optional)
              <input
                aria-label="Total cost basis"
                type="number"
                min="0"
                step="0.00000001"
                value={basis}
                onChange={(e) => setBasis(e.target.value)}
                disabled={saving}
              />
            </label>
          ) : (
            <>
              <label>
                Price per share ({account.base_currency})
                <input
                  aria-label="Price per share"
                  type="number"
                  required
                  min="0.00000001"
                  step="0.00000001"
                  value={price}
                  onChange={(e) => setPrice(e.target.value)}
                  disabled={saving}
                />
              </label>
              <label>
                Fees ({account.base_currency})
                <input
                  aria-label="Trade fees"
                  type="number"
                  required
                  min="0"
                  step="0.00000001"
                  value={fees}
                  onChange={(e) => setFees(e.target.value)}
                  disabled={saving}
                />
              </label>
            </>
          )}
          <label>
            Note (optional)
            <input
              aria-label="Position note"
              maxLength={240}
              value={note}
              onChange={(e) => setNote(e.target.value)}
              disabled={saving}
            />
          </label>
          <p className="form-note">
            {kind === "opening_position"
              ? "Shares already owned when tracking starts; cash is unchanged. Leave total basis blank if unknown. Record before other trades in this security."
              : "Buys use cash including fees; sells add proceeds less fees. Sales use the oldest shares first (FIFO)."}{" "}
            These are records only; no orders are sent to a broker.
          </p>
          <button type="submit" disabled={saving}>
            {saving ? "Saving…" : "Save position entry"}
          </button>
        </form>
      </details>
    </section>
  );
}
