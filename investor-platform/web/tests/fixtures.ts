import { test as base, expect } from "@playwright/test";
import type { Account } from "../src/api";

// Public market data is synthetic in CI. Live-provider verification uses the demo database.
export const performance = {
  start: "2026-01-02",
  end: "2026-01-06",
  value: "1200",
  cash: "200",
  return: "0.20",
  SPY: "0.02",
  QQQ: "0.04",
  excess_spy: "0.18",
  excess_qqq: "0.16",
  fetched_at: "2026-01-07T12:00:00Z",
  source: "Synthetic browser fixture",
  warnings: [],
  holdings: [
    {
      ticker: "AAA",
      exchange: "NYSE",
      quantity: "10",
      close: "100",
      value: "1000",
      weight: "0.8333333",
      basis: null,
      unrealized_pnl: null,
    },
  ],
  series: [
    {
      date: "2026-01-02",
      value: "1000",
      cash: "0",
      portfolio: "0",
      SPY: "0",
      QQQ: "0",
    },
    {
      date: "2026-01-06",
      value: "1200",
      cash: "200",
      portfolio: "0.20",
      SPY: "0.02",
      QQQ: "0.04",
    },
  ],
};

export const test = base.extend<{ account: Account }>({
  account: async ({ request }, use) => {
    const response = await request.post("/api/accounts", {
      data: { name: "Browser test account", base_currency: "USD" },
    });
    expect(response.ok()).toBe(true);
    await use((await response.json()) as Account);
  },
  page: async ({ page, account }, use) => {
    await page.addInitScript((id) => {
      try {
        if (!localStorage.getItem("minerva-portfolio"))
          localStorage.setItem("minerva-portfolio", id);
      } catch {
        // Storage-denied workflows still exercise the app's fallback.
      }
    }, account.id);
    await page.route("**/api/accounts/*/performance", (route) =>
      route.fulfill({ json: performance }),
    );
    await page.route("**/api/accounts/*/valuation", (route) =>
      route.fulfill({ json: { ...performance, complete: true } }),
    );
    await use(page);
  },
});
export { expect };
