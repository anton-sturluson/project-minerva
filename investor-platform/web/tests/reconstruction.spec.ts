import { expect, test } from "./fixtures";

test("shows reconstruction assumptions and preserves them after reload without requesting returns", async ({
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
  let requests = 0;
  await page.route("**/performance", (route) => {
    requests++;
    return route.abort();
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
  await expect(
    page.getByText(/Portfolio vs. index returns are unavailable/),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Compare performance" }),
  ).toBeHidden();
  await page.reload();
  await expect(page.getByLabel("Reconstruction assumptions")).toBeVisible();
  expect(requests).toBe(0);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});
