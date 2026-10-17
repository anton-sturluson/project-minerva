import { useCallback, useEffect, useRef, useState } from "react";
import { api, errorMessage, type Account } from "./api";
import type { Page } from "./App";
import type { Ledger } from "./ledger/ledger";
import { PortfolioOverview } from "./performance/PortfolioOverview";
import { PostMortem } from "./performance/PostMortem";
import { formatExactDecimal, number } from "./format";
import { Trades } from "./ledger/Trades";
import { CashEntryForm } from "./ledger/CashEntryForm";
import { AccountActivity } from "./ledger/AccountActivity";

export function AccountWorkspace({
  account,
  page,
}: {
  account: Account;
  page: Page;
}) {
  const [overviewOpened, setOverviewOpened] = useState(page === "portfolio");
  useEffect(() => {
    if (page === "portfolio") setOverviewOpened(true);
  }, [page]);
  const [ledger, setLedger] = useState<Ledger | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const loadGeneration = useRef(0);
  const load = useCallback(async () => {
    const generation = ++loadGeneration.current;
    setLoading(true);
    setError("");
    try {
      const result = await api<Ledger>(`/accounts/${account.id}/ledger`);
      if (generation !== loadGeneration.current) return;
      setLedger(result);
    } catch (e) {
      if (generation === loadGeneration.current) setError(errorMessage(e));
    } finally {
      if (generation === loadGeneration.current) setLoading(false);
    }
  }, [account.id]);
  useEffect(() => {
    void load();
    return () => {
      loadGeneration.current += 1;
    };
  }, [load]);
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
            {overviewOpened && (
              <PortfolioOverview account={account} ledger={ledger} />
            )}
          </div>
          {page === "post-mortem" && (
            <PostMortem account={account} ledger={ledger} />
          )}
          <div hidden={page !== "activity"}>
            <div className="balance-line">
              <span>
                {account.reconstruction?.cash_method === "recorded"
                  ? "Cash balance"
                  : account.reconstruction?.cash_method === "purchase_shortfall"
                    ? "Cash balance (inferred deposits)"
                    : account.reconstruction &&
                        account.reconstruction.funding_status !== "reconciled"
                      ? "Reconstructed balancing cash"
                      : "Cash balance"}
              </span>
              <strong data-testid="cash-balance">
                {account.base_currency}{" "}
                {account.reconstruction
                  ? number(ledger.balance)
                  : formatExactDecimal(ledger.balance)}
              </strong>
            </div>
            <Trades account={account} onSaved={load} />
            <CashEntryForm
              account={account}
              ledger={ledger}
              loading={loading}
              saving={saving}
              onSavingChange={setSaving}
              onError={setError}
              onMessage={setMessage}
              onSaved={load}
            />
            <AccountActivity
              account={account}
              ledger={ledger}
              loading={loading}
              saving={saving}
              onSaved={load}
              onMessage={setMessage}
            />
          </div>
        </>
      ) : loading ? (
        <p>Loading account records…</p>
      ) : null}
    </div>
  );
}
