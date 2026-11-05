import { useCallback, useEffect, useRef, useState } from "react";
import { api, errorMessage, type Account } from "./api";
import type { Page } from "./App";
import type { Ledger } from "./ledger/ledger";
import { MarketDataStatus } from "./performance/MarketDataStatus";
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
  const [marketRevision, setMarketRevision] = useState(0);
  const previousPage = useRef(page);
  const refreshMarket = useCallback(() => {
    setMarketRevision((revision) => revision + 1);
  }, []);
  useEffect(() => {
    const returned = previousPage.current !== page;
    previousPage.current = page;
    if (page !== "portfolio" && page !== "post-mortem") return;
    const refreshVisible = () => {
      if (document.visibilityState === "visible") refreshMarket();
    };
    if (returned) refreshVisible();
    window.addEventListener("focus", refreshVisible);
    document.addEventListener("visibilitychange", refreshVisible);
    return () => {
      window.removeEventListener("focus", refreshVisible);
      document.removeEventListener("visibilitychange", refreshVisible);
    };
  }, [page, refreshMarket]);
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
      {(page === "portfolio" || page === "post-mortem") && (
        <MarketDataStatus revision={marketRevision} />
      )}
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
              <PortfolioOverview
                account={account}
                ledger={ledger}
                marketRevision={marketRevision}
                onRefreshMarket={refreshMarket}
              />
            )}
          </div>
          {page === "post-mortem" && (
            <PostMortem
              account={account}
              ledger={ledger}
              marketRevision={marketRevision}
            />
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
