import { useEffect, useRef, useState, type FormEvent } from "react";
import { api, errorMessage, type Account } from "./api";
import { exact, labels, today, type Entry, type Holding } from "./records";

type Preview = {
  revision: string;
  previous_balance: string;
  balance: string;
  holdings: Holding[];
  replacement: Entry | null;
};

export function EntrySummary({ entry }: { entry: Entry }) {
  return (
    <p>
      #{entry.id} · {entry.effective_date} · {labels[entry.kind]} ·{" "}
      {entry.currency} {exact(entry.amount)}
      {entry.security && (
        <>
          {" "}
          · {entry.security.ticker} / {entry.security.exchange} ·{" "}
          {exact(entry.quantity!, 0)} shares
          {entry.price !== null && (
            <>
              {" "}
              · price {exact(entry.price)} · fees {exact(entry.fees)}
            </>
          )}
          {entry.kind === "opening_position" && (
            <>
              {" "}
              · basis{" "}
              {entry.cost_basis === null ? "unknown" : exact(entry.cost_basis)}
            </>
          )}
        </>
      )}{" "}
      · {entry.note || "No note"}
    </p>
  );
}

export function Corrections({
  account,
  entry,
  onSaved,
  onCancel,
}: {
  account: Account;
  entry: Entry;
  onSaved: () => Promise<void>;
  onCancel: () => void;
}) {
  const [action, setAction] = useState("replace");
  const [draft, setDraft] = useState({
    kind: entry.kind,
    effective_date: entry.effective_date,
    amount: entry.amount,
    ticker: entry.security?.ticker ?? "",
    exchange: entry.security?.exchange ?? "",
    quantity: entry.quantity ?? "",
    price: entry.price ?? "",
    fees: entry.fees ?? "0",
    cost_basis: entry.cost_basis ?? "",
    note: entry.note,
    reason: "",
  });
  const [preview, setPreview] = useState<Preview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const key = useRef(crypto.randomUUID());
  const panel = useRef<HTMLElement>(null);
  useEffect(() => {
    panel.current?.scrollIntoView({ block: "start" });
  }, []);
  function change(name: keyof typeof draft, value: string) {
    setDraft((d) => ({ ...d, [name]: value }));
    setPreview(null);
    setError("");
    key.current = crypto.randomUUID();
  }
  const position = ["buy", "sell", "opening_position"].includes(draft.kind);
  function replacement() {
    if (action === "void") return null;
    const common = {
      request_key: key.current,
      kind: draft.kind,
      effective_date: draft.effective_date,
      currency: account.base_currency,
      note: draft.note,
    };
    return position
      ? {
          ...common,
          ticker: draft.ticker,
          exchange: draft.exchange,
          quantity: draft.quantity,
          price: draft.kind === "opening_position" ? null : draft.price,
          fees: draft.kind === "opening_position" ? "0" : draft.fees,
          cost_basis:
            draft.kind === "opening_position" && draft.cost_basis !== ""
              ? draft.cost_basis
              : null,
        }
      : { ...common, amount: draft.amount };
  }
  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const result = await api<Preview>(
        `/accounts/${account.id}/entries/${entry.id}/correction${preview ? "" : "?preview=true"}`,
        {
          method: "POST",
          body: JSON.stringify({
            request_key: key.current,
            reason: draft.reason,
            replacement: replacement(),
            expected_revision: preview?.revision ?? null,
          }),
        },
      );
      if (preview) {
        await onSaved();
        onCancel();
      } else setPreview(result);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }
  function field(
    name: keyof typeof draft,
    label: string,
    type = "text",
    required = true,
  ) {
    return (
      <label>
        {label}
        <input
          aria-label={label}
          type={type}
          value={draft[name]}
          required={required}
          max={type === "date" ? today() : undefined}
          step={type === "number" ? "0.00000001" : undefined}
          onChange={(e) => change(name, e.target.value)}
        />
      </label>
    );
  }
  return (
    <section
      ref={panel}
      className="reconstruction"
      aria-label="Correct ledger entry"
    >
      <h3>Correct entry #{entry.id}</h3>
      <EntrySummary entry={entry} />
      <p>Originals stay in correction history. Review before saving.</p>
      {error && (
        <p className="error" role="alert">
          {error} Your draft is preserved. If records changed, edit the draft or
          cancel and reload before previewing again.
        </p>
      )}
      <form onSubmit={(e) => void submit(e)}>
        <fieldset
          disabled={busy || preview !== null}
          className="entry-form correction-fields"
        >
          <legend>Correction</legend>
          <label>
            Action
            <select
              aria-label="Correction action"
              value={action}
              onChange={(e) => {
                setAction(e.target.value);
                setPreview(null);
                key.current = crypto.randomUUID();
              }}
            >
              <option value="replace">Replace entry</option>
              <option value="void">Void entry</option>
            </select>
          </label>
          {action === "replace" && (
            <>
              <label>
                Entry type
                <select
                  aria-label="Replacement type"
                  value={draft.kind}
                  onChange={(e) => change("kind", e.target.value)}
                >
                  {Object.entries(labels).map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </select>
              </label>
              {field("effective_date", "Replacement date", "date")}
              {position ? (
                <>
                  {field("ticker", "Replacement ticker")}
                  {field("exchange", "Replacement exchange")}
                  {field("quantity", "Replacement shares", "number")}
                  {draft.kind === "opening_position" ? (
                    field(
                      "cost_basis",
                      "Replacement total basis (optional)",
                      "number",
                      false,
                    )
                  ) : (
                    <>
                      {field("price", "Replacement price", "number")}
                      {field("fees", "Replacement fees", "number")}
                    </>
                  )}
                </>
              ) : (
                field("amount", "Replacement cash amount", "number")
              )}
              {field("note", "Replacement note", "text", false)}
            </>
          )}
          {field("reason", "Correction reason")}
        </fieldset>
        {preview && (
          <div aria-label="Correction preview">
            <h4>{action === "void" ? "Review void" : "Review replacement"}</h4>
            {preview.replacement ? (
              <EntrySummary entry={preview.replacement} />
            ) : (
              <p>Exclude the original from active records.</p>
            )}
            <p>Reason: {draft.reason}</p>
            <p>
              Cash: {account.base_currency} {exact(preview.previous_balance)} →{" "}
              {exact(preview.balance)}
            </p>
            <details open>
              <summary>Resulting holdings</summary>
              {preview.holdings.length ? (
                <ul>
                  {preview.holdings.map((h) => (
                    <li key={h.security.id}>
                      {h.security.ticker} · {h.security.exchange}:{" "}
                      {exact(h.quantity, 0)} shares · basis{" "}
                      {h.cost_basis === null ? "unknown" : exact(h.cost_basis)}
                    </li>
                  ))}
                </ul>
              ) : (
                <p>No open positions.</p>
              )}
            </details>
            <button
              type="button"
              disabled={busy}
              onClick={() => {
                setPreview(null);
                setError("");
              }}
            >
              Edit draft
            </button>
          </div>
        )}
        <button disabled={busy} type="submit">
          {busy
            ? "Checking…"
            : preview
              ? "Confirm correction"
              : "Preview correction"}
        </button>{" "}
        <button disabled={busy} type="button" onClick={onCancel}>
          Cancel correction
        </button>
      </form>
    </section>
  );
}
