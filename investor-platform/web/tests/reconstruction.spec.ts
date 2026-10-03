import { expect, test, performance } from "./fixtures";

test("shows provisional performance, recovers from failure, and preserves import assumptions", async ({
  page,
}) => {
  await page.route("**/api/account", async (route) => {
    const response = await route.fetch();
    const account = await response.json();
    await route.fulfill({
      json: {
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
  let unavailable = true;
  await page.route("**/performance", (route) => {
    requests++;
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
  await expect(page.getByLabel("Reconstruction assumptions")).toContainText(
    "3 transactions imported · 1 rows excluded · 1 inferred opening positions",
  );
  await page
    .getByText("Import assumptions & excluded rows", { exact: true })
    .click();
  await expect(
    page.getByText("Row 5: Unconfirmed currency", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText(/Quotes temporarily unavailable/)).toBeVisible();
  unavailable = false;
  await page.getByRole("button", { name: "Retry comparison" }).click();
  await expect(
    page.getByText("Opening cash is inferred, not a verified balance.", {
      exact: true,
    }),
  ).toBeHidden();
  await page.getByText("Estimate assumptions", { exact: true }).click();
  await expect(
    page.getByText("Opening cash is inferred, not a verified balance.", {
      exact: true,
    }),
  ).toBeVisible();
  await expect(page.getByLabel("Estimate assumptions")).toContainText(
    "Opening cash is inferred",
  );
  await expect(
    page.getByText("Estimated portfolio return", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Calculate hit rate" }),
  ).toBeHidden();
  await page.reload();
  await expect(page.getByLabel("Estimate assumptions")).toBeVisible();
  expect(requests).toBeGreaterThanOrEqual(3);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});
