import { useRef, useState, type FormEvent } from "react";
import { api, errorMessage, type Account } from "./api";
import {
  today,
  type Entry,
  type PositionKind,
  positionKinds,
  labels,
} from "./records";

export function Trades({
  account,
  onSaved,
}: {
  account: Account;
  onSaved: () => Promise<void>;
}) {
  const [kind, setKind] = useState<PositionKind>("buy");
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
    <section className="positions" aria-label="Trade entry">
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
              onChange={(e) => setKind(e.target.value as PositionKind)}
            >
              {positionKinds.map((kind) => (
                <option key={kind} value={kind}>
                  {labels[kind]}
                </option>
              ))}
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
              ? "Leave basis blank if unknown. Record opening shares before trades."
              : "Fees affect cash and cost basis. Sales use FIFO."}
          </p>
          <button type="submit" disabled={saving}>
            {saving ? "Saving…" : "Save position entry"}
          </button>
        </form>
      </details>
    </section>
  );
}
