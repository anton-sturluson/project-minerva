import type { Account } from "../api";
import type { Ledger } from "../ledger/ledger";
import { Holdings } from "./Holdings";
import { TradeScorecard } from "./TradeScorecard";
import { HitRate } from "./HitRate";
import { PerformanceComparison } from "./PerformanceComparison";

export function PortfolioOverview({
  account,
  ledger,
  marketRevision,
  onRefreshMarket,
}: {
  account: Account;
  ledger: Ledger;
  marketRevision: number;
  onRefreshMarket: () => void;
}) {
  return (
    <>
      <div id="decisions" className="decisions">
        <TradeScorecard
          account={account}
          ledger={ledger}
          marketRevision={marketRevision}
        />
        {!account.reconstruction && (
          <HitRate
            key={`${account.id}:${ledger.entries.map((e) => e.id).join(",")}`}
            accountId={account.id}
            marketRevision={marketRevision}
          />
        )}
      </div>

      <Holdings
        ledger={ledger}
        accountId={account.id}
        marketRevision={marketRevision}
        onRefreshMarket={onRefreshMarket}
      />
      <PerformanceComparison
        account={account}
        ledger={ledger}
        marketRevision={marketRevision}
      />
    </>
  );
}
