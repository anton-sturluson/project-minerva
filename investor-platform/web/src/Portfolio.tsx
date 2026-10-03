import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api, errorMessage, type Account } from "./api";

import { CashLedger } from "./CashLedger";

export function Portfolio() {
  const [account, setAccount] = useState<Account | null>(null);
  const [loading, setLoading] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [name, setName] = useState("");
  const [currency, setCurrency] = useState("");
  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setAccount(await api<Account | null>("/account"));
      setLoaded(true);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);
  async function create(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError("");
    try {
      setAccount(
        await api<Account>("/account", {
          method: "POST",
          body: JSON.stringify({ name, base_currency: currency }),
        }),
      );
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setSaving(false);
    }
  }
  return (
    <section
      id="portfolio"
      className="portfolio"
      aria-labelledby="portfolio-heading"
    >
      <h1 id="portfolio-heading">
        <span aria-hidden="true">✳ </span>My portfolio
      </h1>
      {error && (
        <div className="error" role="alert">
          <p>{error}</p>
          <button
            type="button"
            onClick={() => void load()}
            disabled={loading || saving}
          >
            Reload account
          </button>
        </div>
      )}
      {loading ? (
        <p>Opening your records…</p>
      ) : !loaded ? null : account ? (
        <>
          <div className="account-line">
            <h3>{account.name}</h3>
            <span>{account.base_currency} · Base currency</span>
          </div>
          {account.reconstruction && (
            <aside
              className="reconstruction"
              aria-label="Reconstruction assumptions"
            >
              <strong>Testing copy · incomplete transaction history</strong>
              <p>
                Opening shares and cash are inferred minimums, not broker
                balances. Holdings and performance are provisional until the
                records are reconciled.
              </p>
              <p>
                {account.reconstruction.imported_trades} transactions imported ·{" "}
                {account.reconstruction.skipped.length} rows excluded ·{" "}
                {Object.keys(account.reconstruction.opening_positions).length}{" "}
                inferred opening positions.
              </p>
              <details>
                <summary>Import assumptions &amp; excluded rows</summary>
                <p>
                  Minimum inferred opening cash: USD{" "}
                  {account.reconstruction.opening_cash}. This is balancing cash,
                  not a historical balance.
                </p>
                <p>
                  Trade amounts use underlying shares and prices where
                  available, rounded to eight decimal places. CSV imports use
                  totals divided by recorded shares. No separate fees were
                  supplied. {account.reconstruction.price_discrepancies.length}{" "}
                  rows have a total that differs from displayed shares × price.
                  Original rows are preserved in PostgreSQL.
                </p>
                {Object.entries(account.reconstruction.opening_positions).map(
                  ([ticker, quantity]) => (
                    <p key={ticker}>
                      {ticker}: {quantity} inferred shares, unknown acquisition
                      date and cost basis.
                    </p>
                  ),
                )}
                {account.reconstruction.skipped.map((row) => (
                  <p key={row.row}>
                    Row {row.row}: {row.reason}
                  </p>
                ))}
              </details>
            </aside>
          )}
          <CashLedger account={account} />
        </>
      ) : (
        <>
          <p>
            Start with one account and the currency you keep its records in.
          </p>
          <form onSubmit={(event) => void create(event)} className="entry-form">
            <label>
              Account name
              <input
                required
                maxLength={80}
                value={name}
                onChange={(e) => setName(e.target.value)}
                autoComplete="off"
              />
            </label>
            <label>
              Base currency
              <select
                aria-label="Base currency"
                required
                value={currency}
                onChange={(e) => setCurrency(e.target.value)}
              >
                <option value="">Choose a currency</option>
                {[
                  "USD",
                  "EUR",
                  "GBP",
                  "CAD",
                  "AUD",
                  "JPY",
                  "CHF",
                  "HKD",
                  "SGD",
                ].map((code) => (
                  <option key={code} value={code}>
                    {code}
                  </option>
                ))}
              </select>
            </label>
            <p className="form-note">
              Currency is fixed for this account. One account for now.
            </p>
            <button disabled={saving} type="submit">
              {saving ? "Saving…" : "Create account"}
            </button>
          </form>
        </>
      )}
    </section>
  );
}
