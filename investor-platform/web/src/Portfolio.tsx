import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api, errorMessage, type Account } from "./api";
import type { Page } from "./App";
import { CashLedger } from "./CashLedger";

const selectionKey = "minerva-portfolio";
function savedSelection() {
  try {
    return localStorage.getItem(selectionKey) ?? "";
  } catch {
    return "";
  }
}

export function Portfolio({ page }: { page: Page }) {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [selected, setSelected] = useState(savedSelection);
  const account = accounts.find((item) => item.id === selected) ?? null;
  const [loading, setLoading] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [currency, setCurrency] = useState("");
  function select(id: string) {
    setSelected(id);
    try {
      localStorage.setItem(selectionKey, id);
    } catch {
      /* Optional persistence. */
    }
  }
  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const list = await api<Account[]>("/accounts");
      setAccounts(list);
      setSelected((previous) =>
        list.some((item) => item.id === previous)
          ? previous
          : (list[0]?.id ?? ""),
      );
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
      const created = await api<Account>("/accounts", {
        method: "POST",
        body: JSON.stringify({ name, base_currency: currency }),
      });
      setAccounts((current) =>
        current.some((a) => a.id === created.id)
          ? current
          : [...current, created],
      );
      select(created.id);
      setCreating(false);
      setName("");
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
            Reload portfolios
          </button>
        </div>
      )}
      {loading ? (
        <p>Opening your records…</p>
      ) : !loaded ? null : (
        <>
          {account && (
            <div className="portfolio-picker">
              <label>
                Portfolio
                <select
                  aria-label="Portfolio"
                  value={account.id}
                  disabled={saving}
                  onChange={(e) => select(e.target.value)}
                >
                  {accounts.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.name}
                    </option>
                  ))}
                </select>
              </label>
              <span>{account.base_currency}</span>
              <button
                type="button"
                disabled={saving}
                onClick={() => {
                  setCreating(true);
                  setCurrency(account.base_currency);
                }}
              >
                New portfolio
              </button>
            </div>
          )}
          {(!account || creating) && (
            <form
              onSubmit={(event) => void create(event)}
              className="entry-form"
              aria-label="New portfolio"
            >
              <label>
                Portfolio name
                <input
                  required
                  maxLength={80}
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  autoComplete="off"
                  disabled={saving}
                />
              </label>
              <label>
                Base currency
                <select
                  aria-label="Base currency"
                  required
                  value={currency}
                  onChange={(e) => setCurrency(e.target.value)}
                  disabled={saving}
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
              <button disabled={saving} type="submit">
                {saving ? "Saving…" : "Create portfolio"}
              </button>
              {account && (
                <button
                  disabled={saving}
                  type="button"
                  onClick={() => setCreating(false)}
                >
                  Cancel
                </button>
              )}
            </form>
          )}
          {account && (
            <CashLedger key={account.id} account={account} page={page} />
          )}
        </>
      )}
    </section>
  );
}
