import { useState } from "react";
import type { Account } from "../api";
import { formatExactDecimal } from "../format";
import { Corrections, EntrySummary } from "./Corrections";
import {
  labels,
  isInKind,
  incomeSecurities,
  type Entry,
  type Ledger,
} from "./ledger";

export function AccountActivity({
  account,
  ledger,
  loading,
  saving,
  onSaved,
  onMessage,
}: {
  account: Account;
  ledger: Ledger;
  loading: boolean;
  saving: boolean;
  onSaved: () => Promise<void>;
  onMessage: (message: string) => void;
}) {
  const [correcting, setCorrecting] = useState<Entry | null>(null);
  return (
    <details className="entry-panel">
      <summary>Account activity</summary>
      {correcting && (
        <Corrections
          key={correcting.id}
          account={account}
          entry={correcting}
          securities={incomeSecurities(ledger.entries)}
          onSaved={async () => {
            await onSaved();
            onMessage("Correction saved. Original retained in audit history.");
          }}
          onCancel={() => setCorrecting(null)}
        />
      )}
      {!!ledger.corrections?.length && (
        <details className="entry-panel">
          <summary>Correction history ({ledger.corrections.length})</summary>
          {ledger.corrections.map((c) => (
            <article key={c.id}>
              <h4>
                {c.replacement ? "Replaced" : "Voided"} entry #{c.original.id}
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
                    {formatExactDecimal(e.amount)}
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
                          <dd>{formatExactDecimal(e.quantity!, 0)}</dd>
                          {e.price !== null && (
                            <>
                              <dt>Price per share</dt>
                              <dd>{formatExactDecimal(e.price)}</dd>
                              <dt>Fees</dt>
                              <dd>{formatExactDecimal(e.fees)}</dd>
                            </>
                          )}
                          {isInKind(e.kind) && (
                            <>
                              <dt>Opening total basis</dt>
                              <dd>
                                {e.cost_basis === null
                                  ? "Unknown"
                                  : formatExactDecimal(e.cost_basis)}
                              </dd>
                            </>
                          )}
                          {e.kind === "sell" && (
                            <>
                              <dt>Realized P&amp;L (FIFO, after fees)</dt>
                              <dd>
                                {e.realized_pnl === null
                                  ? "Unknown: opening basis unavailable"
                                  : formatExactDecimal(e.realized_pnl)}
                              </dd>
                            </>
                          )}
                          <dt>Recorded</dt>
                          <dd>{e.created_at}</dd>
                          <dt>Note</dt>
                          <dd>{e.note || "—"}</dd>
                        </dl>
                      </details>
                    ) : e.kind === "deposit" &&
                      e.note ===
                        "INFERRED purchase funding shortfall; historical deposit timing is assumed." ? (
                      "—"
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
    </details>
  );
}
