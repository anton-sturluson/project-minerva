import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";
import { api, errorMessage, type Account } from "./api";
import { Corrections, EntrySummary } from "./Corrections";
import { Tracker } from "./Tracker";
import { number } from "./format";
import { Trades } from "./Trades";
import {
  exact,
  today,
  labels,
  type Entry,
  type Ledger,
  type CashKind,
  cashKinds,
} from "./records";

export function CashLedger({ account }: { account: Account }) {
  const [correcting, setCorrecting] = useState<Entry | null>(null);
  const [ledger, setLedger] = useState<Ledger | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [kind, setKind] = useState<CashKind>("opening_cash");
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
            <span>
              {account.reconstruction
                ? "Reconstructed balancing cash"
                : "Cash balance"}
            </span>
            <strong data-testid="cash-balance">
              {account.base_currency}{" "}
              {account.reconstruction
                ? number(ledger.balance)
                : exact(ledger.balance)}
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
                onChange={(e) => setKind(e.target.value as CashKind)}
                disabled={saving}
              >
                {cashKinds
                  .filter(
                    (kind) => kind !== "opening_cash" || !ledger.entries.length,
                  )
                  .map((kind) => (
                    <option key={kind} value={kind}>
                      {labels[kind]}
                    </option>
                  ))}
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
            {kind === "income" && (
              <p className="form-note">
                Record gross dividends on their ex-date.
              </p>
            )}
            {kind === "opening_cash" && (
              <p className="form-note">Cash held when tracking begins.</p>
            )}
            <button disabled={saving || loading} type="submit">
              {saving ? "Saving…" : "Save cash entry"}
            </button>
          </form>
          <h3 className="activity-heading">Activity</h3>
          {correcting && (
            <Corrections
              key={correcting.id}
              account={account}
              entry={correcting}
              onSaved={async () => {
                await load();
                setMessage(
                  "Correction saved. Original retained in audit history.",
                );
              }}
              onCancel={() => setCorrecting(null)}
            />
          )}
          {!!ledger.corrections?.length && (
            <details className="entry-panel">
              <summary>
                Correction history ({ledger.corrections.length})
              </summary>
              {ledger.corrections.map((c) => (
                <article key={c.id}>
                  <h4>
                    {c.replacement ? "Replaced" : "Voided"} entry #
                    {c.original.id}
                  </h4>
                  <p>
                    {c.reason} · {c.created_at}
                  </p>
                  <EntrySummary entry={c.original} />
                  {c.replacement && <EntrySummary entry={c.replacement} />}
                </article>
              ))}
            </details>
          )}
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
                    <th>Correction</th>
                  </tr>
                </thead>
                <tbody>
                  {ledger.entries.map((e) => (
                    <tr key={e.id}>
                      <td>{e.effective_date}</td>
                      <td>
                        {labels[e.kind]}
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
                      <td>
                        <button
                          disabled={saving || loading || correcting !== null}
                          aria-label={`Correct entry ${e.id}`}
                          onClick={() => setCorrecting(e)}
                        >
                          Correct
                        </button>
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
