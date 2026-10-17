import type { Account } from "../api";
import type { Ledger } from "../ledger/ledger";
import { Holdings } from "./Holdings";
import { TradeScorecard } from "./TradeScorecard";
import { HitRate } from "./HitRate";
import { PerformanceComparison } from "./PerformanceComparison";

export function PortfolioOverview({
  account,
  ledger,
}: {
  account: Account;
  ledger: Ledger;
}) {
  return (
    <>
      <div id="decisions" className="decisions">
        <TradeScorecard account={account} ledger={ledger} />
        {!account.reconstruction && (
          <HitRate
            key={`${account.id}:${ledger.entries.map((e) => e.id).join(",")}`}
            accountId={account.id}
          />
        )}
      </div>

      <Holdings ledger={ledger} accountId={account.id} />
      <PerformanceComparison account={account} ledger={ledger} />
    </>
  );
}
