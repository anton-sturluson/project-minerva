import { expect, test, performance } from "./fixtures";

const security = {
  id: "00000000-0000-4000-8000-000000000010",
  ticker: "AAA",
  exchange: "NYSE",
  currency: "USD",
};

test("compares exclusions and CAGR, preserves real holdings, clears selections and recovers", async ({
  page,
}) => {
  await page.route("**/ledger", (route) =>
    route.fulfill({
      json: {
        balance: "200",
        currency: "USD",
        holdings: [],
        entries: [
          {
            id: 1,
            kind: "buy",
            effective_date: "2024-01-02",
            security,
            amount: "1000",
            quantity: "10",
            price: "100",
            fees: "0",
            cost_basis: null,
            note: "Synthetic fixture",
            currency: "USD",
            created_at: "2024-01-02T12:00:00Z",
          },
        ],
      },
    }),
  );
  let blocked = false;
  let received: string[] = [];
  const cagr = { portfolio: "0.0954", SPY: "0.01", QQQ: "0.0198" };
  await page.route("**/performance", (route) => {
    received = route.request().postDataJSON().exclude_security_ids ?? [];
    return route.fulfill({
      json: {
        ...performance,
        start: "2024-01-02",
        cagr,
        scenario_error:
          received.length && blocked
            ? "Scenario unavailable: synthetic funding gap"
            : null,
        scenario:
          received.length && !blocked
            ? {
                ...performance,
                return: "0",
                cagr: { ...cagr, portfolio: "0" },
                excluded: [security],
                series: performance.series.map((p) => ({
                  ...p,
                  portfolio: "0",
                })),
              }
            : null,
      },
    });
  });
  await page.goto("/");
  const summary = page.getByLabel("Performance summary");
  await expect(summary).toContainText("9.54%");
  await page.getByText("Exclude stocks", { exact: true }).click();
  await page.getByRole("checkbox", { name: "AAA · NYSE" }).check();
  await expect(page.getByLabel("Holdings", { exact: true })).toContainText(
    "AAA",
  );
  await page.getByRole("button", { name: "Compare performance" }).click();
  await expect(summary).toContainText("Without excluded stocks");
  expect(received).toEqual([security.id]);
  await expect(
    summary.getByRole("row").filter({ hasText: "Without excluded stocks" }),
  ).toContainText("0.00%");
  await expect(page.locator(".scenario-line")).toHaveAttribute(
    "points",
    "58,195 795,195",
  );
  await expect(
    page.getByRole("img", { name: /Cumulative portfolio/ }),
  ).toBeVisible();
  await expect(page.getByLabel("Holdings", { exact: true })).toContainText(
    "AAA",
  );
  await page.getByText("Daily values", { exact: true }).click();
  await expect(page.getByLabel("Daily performance")).toContainText(
    "Without excluded stocks",
  );
  blocked = true;
  await page.getByRole("button", { name: "Compare performance" }).click();
  await expect(page.getByRole("alert")).toContainText(
    "Scenario unavailable: synthetic funding gap",
  );
  await expect(page.locator(".scenario-line")).toHaveCount(0);
  await expect(summary).toContainText("20.00%");
  await page.getByRole("button", { name: "Clear exclusions" }).click();
  await page.getByRole("button", { name: "Compare performance" }).click();
  await expect(page.getByRole("alert")).toBeHidden();
  expect(received).toEqual([]);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});
