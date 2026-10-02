import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";
import { api, errorMessage, type Account } from "./api";
import { Tracker } from "./Tracker";
import { Trades } from "./Trades";
import { exact, today, labels, type Entry, type Ledger } from "./records";

export function CashLedger({ account }: { account: Account }) {
  const [ledger, setLedger] = useState<Ledger | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [kind, setKind] = useState("opening_cash");
  const [date, setDate] = useState(today());
  const [amount, setAmount] = useState("");
  const [note, setNote] = useState("");
  const retry = useRef<{ body: string; key: string } | null>(null);
  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const result = await api<Ledger>(`/accounts/${account.id}/ledger`);
      setLedger(result);
      if (result.entries.length)
        setKind((current) =>
          current === "opening_cash" ? "deposit" : current,
        );
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setLoading(false);
    }
  }, [account.id]);
  useEffect(() => {
    void load();
  }, [load]);
  async function save(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError("");
    setMessage("");
    const payload = {
      kind,
      effective_date: date,
      amount,
      currency: account.base_currency,
      note,
    };
    const body = JSON.stringify(payload);
    if (retry.current?.body !== body)
      retry.current = { body, key: crypto.randomUUID() };
    try {
      await api<Entry>(`/accounts/${account.id}/cash`, {
        method: "POST",
        body: JSON.stringify({ ...payload, request_key: retry.current.key }),
      });
      retry.current = null;
      setAmount("");
      setNote("");
      setMessage("Cash entry saved.");
      await load();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setSaving(false);
    }
  }
  return (
    <div className="ledger">
      {error && (
        <div className="error" role="alert">
          <p>{error}</p>
          <button disabled={saving || loading} onClick={() => void load()}>
            Reload records
          </button>
        </div>
      )}
      {message && (
        <p className="save-message" aria-live="polite">
          {message}
        </p>
      )}
      {ledger ? (
        <>
          <Tracker account={account} ledger={ledger} />
          <div className="balance-line">
            <span>Cash balance</span>
            <strong data-testid="cash-balance">
              {account.base_currency} {exact(ledger.balance)}
            </strong>
          </div>
          <Trades account={account} holdings={ledger.holdings} onSaved={load} />
          <h3>Record cash</h3>
          <form className="entry-form" onSubmit={(e) => void save(e)}>
            <label>
              Entry type
              <select
                aria-label="Entry type"
                value={kind}
                onChange={(e) => setKind(e.target.value)}
                disabled={saving}
              >
                {!ledger.entries.length && (
                  <option value="opening_cash">Opening cash</option>
                )}
                <option value="deposit">Deposit</option>
                <option value="withdrawal">Withdrawal</option>
                <option value="income">Investment income</option>
              </select>
            </label>
            <label>
              Effective date (UTC)
              <input
                aria-label="Cash effective date"
                type="date"
                required
                max={today()}
                value={date}
                onChange={(e) => setDate(e.target.value)}
                disabled={saving}
              />
            </label>
            <label>
              Cash change ({account.base_currency})
              <input
                aria-label="Cash amount"
                required
                inputMode="decimal"
                type="number"
                min={kind === "opening_cash" ? "0" : "0.00000001"}
                step="0.00000001"
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
                disabled={saving}
              />
            </label>
            <label>
              Note (optional)
              <input
                aria-label="Cash note"
                maxLength={240}
                value={note}
                onChange={(e) => setNote(e.target.value)}
                disabled={saving}
              />
            </label>
            <p className="form-note">
              {kind === "opening_cash"
                ? "Your balance when tracking starts, not a past deposit."
                : "Entries are checked against the full dated history. Cash cannot go below zero."}{" "}
              Income is investment return, not a deposit; record gross dividends
              on their ex-date for comparisons. Same-day entries follow the
              order saved. Corrections come in a later update.
            </p>
            <button disabled={saving || loading} type="submit">
              {saving ? "Saving…" : "Save cash entry"}
            </button>
          </form>
          <h3 className="activity-heading">Activity</h3>
          {ledger.entries.length ? (
            <div
              className="table-scroll"
              tabIndex={0}
              aria-label="Account activity"
            >
              <table>
                <thead>
                  <tr>
                    <th>Date</th>
                    <th>Entry</th>
                    <th className="number">
                      Cash change ({account.base_currency})
                    </th>
                    <th>Details / note</th>
                  </tr>
                </thead>
                <tbody>
                  {ledger.entries.map((e) => (
                    <tr key={e.id}>
                      <td>{e.effective_date}</td>
                      <td>
                        {labels[e.kind] ?? e.kind}
                        {e.security && <> · {e.security.ticker}</>}
                      </td>
                      <td className="number">
                        {["withdrawal", "buy"].includes(e.kind) ? "−" : ""}
                        {exact(e.amount)}
                      </td>
                      <td>
                        {e.security ? (
                          <details>
                            <summary>Entry #{e.id}</summary>
                            <dl className="entry-detail">
                              <dt>Security</dt>
                              <dd>
                                {e.security.ticker} · {e.security.exchange} ·{" "}
                                {e.currency}
                              </dd>
                              <dt>Shares</dt>
                              <dd>{exact(e.quantity!, 0)}</dd>
                              {e.price !== null && (
                                <>
                                  <dt>Price per share</dt>
                                  <dd>{exact(e.price)}</dd>
                                  <dt>Fees</dt>
                                  <dd>{exact(e.fees)}</dd>
                                </>
                              )}
                              {e.kind === "opening_position" && (
                                <>
                                  <dt>Opening total basis</dt>
                                  <dd>
                                    {e.cost_basis === null
                                      ? "Unknown"
                                      : exact(e.cost_basis)}
                                  </dd>
                                </>
                              )}
                              {e.kind === "sell" && (
                                <>
                                  <dt>Realized P&amp;L (FIFO, after fees)</dt>
                                  <dd>
                                    {e.realized_pnl === null
                                      ? "Unknown: opening basis unavailable"
                                      : exact(e.realized_pnl)}
                                  </dd>
                                </>
                              )}
                              <dt>Recorded</dt>
                              <dd>{e.created_at}</dd>
                              <dt>Note</dt>
                              <dd>{e.note || "—"}</dd>
                            </dl>
                          </details>
                        ) : (
                          e.note || "—"
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p>No activity yet.</p>
          )}
        </>
      ) : loading ? (
        <p>Loading account records…</p>
      ) : null}
    </div>
  );
}
