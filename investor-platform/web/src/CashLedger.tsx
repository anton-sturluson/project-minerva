import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";
import { api, errorMessage, type Account } from "./api";
import { Corrections, EntrySummary } from "./Corrections";
import type { Page } from "./App";
import { Tracker } from "./Tracker";
import { number } from "./format";
import { IncomeFields, emptyIncome, incomePayload } from "./IncomeFields";
import { Trades } from "./Trades";
import {
  exact,
  today,
  labels,
  isInKind,
  type Entry,
  type Ledger,
  type CashKind,
  cashKinds,
  incomeSecurities,
} from "./records";

export function CashLedger({
  account,
  page,
}: {
  account: Account;
  page: Page;
}) {
  const [correcting, setCorrecting] = useState<Entry | null>(null);
  const [ledger, setLedger] = useState<Ledger | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [kind, setKind] = useState<CashKind>("opening_cash");
  const [date, setDate] = useState(today());
  const [amount, setAmount] = useState("");
  const [income, setIncome] = useState(emptyIncome);
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
      ...(kind === "income" ? incomePayload(income) : {}),
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
          <div hidden={page !== "portfolio"}>
            <Tracker account={account} ledger={ledger} />
          </div>
          <div hidden={page !== "activity"}>
            <div className="balance-line">
              <span>
                {account.reconstruction &&
                account.reconstruction.funding_status !== "reconciled"
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
            <Trades account={account} onSaved={load} />
            <details className="entry-panel">
              <summary>Record cash</summary>
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
                        (kind) =>
                          kind !== "opening_cash" || !ledger.entries.length,
                      )
                      .map((kind) => (
                        <option key={kind} value={kind}>
                          {labels[kind]}
                        </option>
                      ))}
                  </select>
                </label>
                <label>
                  Effective date (New York)
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
                  <IncomeFields
                    value={income}
                    paymentDate={date}
                    securities={incomeSecurities(ledger.entries)}
                    onChange={(field, value) =>
                      setIncome((current) => ({ ...current, [field]: value }))
                    }
                  />
                )}
                {kind === "opening_cash" && (
                  <p className="form-note">Cash held when tracking begins.</p>
                )}
                <button disabled={saving || loading} type="submit">
                  {saving ? "Saving…" : "Save cash entry"}
                </button>
              </form>
            </details>
            <details className="entry-panel">
              <summary>Account activity</summary>
              {correcting && (
                <Corrections
                  key={correcting.id}
                  account={account}
                  entry={correcting}
                  securities={incomeSecurities(ledger.entries)}
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
                            {e.income_kind && <> · {e.income_kind}</>}
                            {e.income_security && (
                              <>
                                {" "}
                                · {e.income_security.ticker}{" "}
                                {e.accrual_date && <>· ex {e.accrual_date}</>}
                              </>
                            )}
                          </td>
                          <td className="number">
                            {["withdrawal", "expense", "buy"].includes(e.kind)
                              ? "−"
                              : ""}
                            {exact(e.amount)}
                          </td>
                          <td>
                            {e.security ? (
                              <details>
                                <summary>Entry #{e.id}</summary>
                                <dl className="entry-detail">
                                  <dt>Security</dt>
                                  <dd>
                                    {e.security.ticker} · {e.security.exchange}{" "}
                                    · {e.currency}
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
                                  {isInKind(e.kind) && (
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
                                      <dt>
                                        Realized P&amp;L (FIFO, after fees)
                                      </dt>
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
                              disabled={
                                saving || loading || correcting !== null
                              }
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
            </details>
          </div>
        </>
      ) : loading ? (
        <p>Loading account records…</p>
      ) : null}
    </div>
  );
}
