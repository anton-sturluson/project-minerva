import { expect, test } from "@playwright/test";

test("compares dated returns, explains outage, and invalidates old results", async ({
  page,
}) => {
  // Fixed market response keeps CI independent of Yahoo availability; real feed tested manually.
  let fail = false;
  await page.route("**/api/accounts/*/ledger", (route) =>
    route.fulfill({
      json: {
        currency: "USD",
        balance: "1000",
        holdings: [],
        entries: [
          {
            id: 1,
            kind: "opening_cash",
            effective_date: "2026-01-02",
            amount: "1000",
            currency: "USD",
            note: "Synthetic fixture",
            created_at: "2026-01-02T12:00:00Z",
            security: null,
          },
        ],
      },
    }),
  );
  await page.route("**/api/accounts/*/performance", (route) =>
    fail
      ? route.fulfill({
          status: 503,
          json: { detail: "Market data is unavailable. Retry the comparison." },
        })
      : route.fulfill({
          json: {
            start: "2026-01-02",
            end: "2026-01-06",
            value: "1200",
            cash: "200",
            return: "0.10",
            SPY: "0.02",
            QQQ: "0.04",
            excess_spy: "0.08",
            excess_qqq: "0.06",
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
                portfolio: "0.10",
                SPY: "0.02",
                QQQ: "0.04",
              },
            ],
          },
        }),
  );
  await page.route("**/statistics", (route) =>
    route.fulfill({
      status: 503,
      json: { detail: "Scorecard temporarily unavailable." },
    }),
  );
  await page.goto("/");
  await expect(
    page.getByRole("button", { name: "Retry scorecard" }),
  ).toBeVisible();
  await page.getByLabel("Performance start").fill("2026-01-02");
  await page.getByLabel("Performance end").fill("2026-01-06");
  await page.getByRole("button", { name: "Compare performance" }).click();
  await expect(
    page.getByText("Closing value (USD)", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("img", { name: /Cumulative portfolio/ }),
  ).toBeVisible();
  // Retrying the independent scorecard must preserve a successful comparison.
  await page.unroute("**/statistics");
  await page.getByRole("button", { name: "Retry scorecard" }).click();
  await expect(page.getByTestId("win-rate")).toBeVisible();
  await expect(
    page.getByText("Closing value (USD)", { exact: true }),
  ).toBeVisible();
  await page.getByText("Daily values", { exact: true }).click();
  await expect(
    page.getByLabel("Daily performance", { exact: true }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  fail = true;
  await page.getByRole("button", { name: "Compare performance" }).click();
  await expect(page.getByRole("alert")).toContainText(
    "Market data is unavailable",
  );
  await expect(
    page.getByText("Closing value (USD)", { exact: true }),
  ).toBeHidden();
  fail = false;
  await page.getByRole("button", { name: "Compare performance" }).click();
  await expect(
    page.getByText("Closing value (USD)", { exact: true }),
  ).toBeVisible();
});
