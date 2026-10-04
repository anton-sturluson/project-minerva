import { expect, test, performance } from "./fixtures";

test("shows provisional performance, recovers from failure, and keeps provisional status without import prose", async ({
  page,
}) => {
  await page.route("**/api/accounts", async (route) => {
    const response = await route.fetch();
    const [account] = await response.json();
    await route.fulfill({
      json: [
        {
          ...account,
          reconstruction: {
            warning:
              "Incomplete transaction reconstruction for testing. Opening shares and cash are inferred minimums, not broker balances.",
            source_sha256: "synthetic",
            imported_trades: 3,
            skipped: [{ row: 5, reason: "Unconfirmed currency" }],
            opening_cash: "41",
            opening_positions: { "AAA · NASDAQ": "3" },
            price_discrepancies: [3],
          },
        },
      ],
    });
  });
  await page.route("**/api/accounts/*/ledger", async (route) => {
    const response = await route.fetch();
    const ledger = await response.json();
    await route.fulfill({
      json: {
        ...ledger,
        entries: ledger.entries.map((e: Record<string, unknown>) => ({
          ...e,
          effective_date: "2026-01-02",
        })),
      },
    });
  });
  let requests = 0;
  let latestPeriod: { start: string; baseline?: string } | undefined;
  let unavailable = true;
  await page.route("**/performance", (route) => {
    requests++;
    latestPeriod = route.request().postDataJSON();
    return unavailable
      ? route.fulfill({
          status: 503,
          json: { detail: "Quotes temporarily unavailable" },
        })
      : route.fulfill({
          json: {
            ...performance,
            provisional: true,
            modeled_income: "6",
            assumptions: ["Opening cash is inferred, not a verified balance."],
          },
        });
  });
  await page.goto("/");
  await expect(page.getByText(/Quotes temporarily unavailable/)).toBeVisible();
  expect(latestPeriod?.baseline).toBeUndefined();
  expect(latestPeriod?.start).toBe("2026-01-02");
  unavailable = false;
  await page.getByRole("button", { name: "Retry comparison" }).click();
  await expect(
    page.getByText("Estimated portfolio return", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Calculate hit rate" }),
  ).toBeHidden();
  // Full history stays explicit; failure does not remove current holdings or the recent option.
  unavailable = true;
  await page.getByRole("button", { name: "Full history", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText(
    "Quotes temporarily unavailable",
  );
  expect(latestPeriod?.start).toBe("2026-01-02");
  expect(latestPeriod?.baseline).toBeUndefined();
  unavailable = false;
  await page.getByRole("button", { name: "Last 90 days", exact: true }).click();
  await expect(
    page.getByText("Estimated portfolio return", { exact: true }),
  ).toBeVisible();
  expect(latestPeriod?.baseline).toBe("recorded");
  await page.reload();
  await expect(
    page.getByText("Estimated portfolio return", { exact: true }),
  ).toBeVisible();
  expect(latestPeriod?.baseline).toBeUndefined();
  expect(latestPeriod?.start).toBe("2026-01-02");
  await expect(
    page.getByRole("heading", { name: "Provisional portfolio vs. the market" }),
  ).toBeVisible();
  await expect(
    page.getByText("Import assumptions & excluded rows", { exact: true }),
  ).toHaveCount(0);
  expect(requests).toBeGreaterThanOrEqual(3);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});
