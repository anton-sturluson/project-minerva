import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api, errorMessage, type Account } from "./api";

import type { Page } from "./App";
import { CashLedger } from "./CashLedger";

export function Portfolio({ page }: { page: Page }) {
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
      id={page === "activity" ? "activity" : "portfolio"}
      className="portfolio"
      aria-labelledby="portfolio-heading"
    >
      <h1 id="portfolio-heading">
        <span aria-hidden="true">✳ </span>
        {page === "activity" ? "Activity" : "My portfolio"}
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
            <span>{account.base_currency}</span>
          </div>
          <CashLedger account={account} page={page} />
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
