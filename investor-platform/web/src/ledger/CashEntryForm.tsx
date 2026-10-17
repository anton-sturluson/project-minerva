import { useIdempotencyKey } from "./useIdempotencyKey";
import { useEffect, useState, type FormEvent } from "react";
import { api, errorMessage, type Account } from "../api";
import { newYorkToday } from "../marketDates";
import { IncomeFields, emptyIncome, incomePayload } from "./IncomeFields";
import {
  cashKinds,
  labels,
  incomeSecurities,
  type CashKind,
  type Entry,
  type Ledger,
} from "./ledger";

export function CashEntryForm({
  account,
  ledger,
  loading,
  saving,
  onSavingChange,
  onError,
  onMessage,
  onSaved,
}: {
  account: Account;
  ledger: Ledger;
  loading: boolean;
  saving: boolean;
  onSavingChange: (saving: boolean) => void;
  onError: (error: string) => void;
  onMessage: (message: string) => void;
  onSaved: () => Promise<void>;
}) {
  const [kind, setKind] = useState<CashKind>("opening_cash");
  const [date, setDate] = useState(newYorkToday());
  const [amount, setAmount] = useState("");
  const [income, setIncome] = useState(emptyIncome);
  const [note, setNote] = useState("");
  const requestKey = useIdempotencyKey();
  useEffect(() => {
    if (ledger.entries.length)
      setKind((current) => (current === "opening_cash" ? "deposit" : current));
  }, [ledger.entries.length]);
  async function save(event: FormEvent) {
    event.preventDefault();
    onSavingChange(true);
    onError("");
    onMessage("");
    const payload = {
      kind,
      effective_date: date,
      amount,
      currency: account.base_currency,
      note,
      ...(kind === "income" ? incomePayload(income) : {}),
    };
    const body = JSON.stringify(payload);
    const key = requestKey.keyFor(body);
    try {
      await api<Entry>(`/accounts/${account.id}/cash`, {
        method: "POST",
        body: JSON.stringify({ ...payload, request_key: key }),
      });
      requestKey.reset();
      setAmount("");
      setNote("");
      onMessage("Cash entry saved.");
      await onSaved();
    } catch (e) {
      onError(errorMessage(e));
    } finally {
      onSavingChange(false);
    }
  }
  return (
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
          Effective date (New York)
          <input
            aria-label="Cash effective date"
            type="date"
            required
            max={newYorkToday()}
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
  );
}
