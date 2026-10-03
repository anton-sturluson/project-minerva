import { expect, test } from "@playwright/test";

test("creates an account and keeps it after reload", async ({ page }) => {
  await page.goto("/#portfolio");
  await expect(page.getByText("Opening your records…")).toBeHidden();
  if (await page.getByLabel("Account name", { exact: true }).isVisible()) {
    await page
      .getByLabel("Account name", { exact: true })
      .fill("Browser test account");
    await page.getByLabel("Base currency", { exact: true }).selectOption("USD");
    await page
      .getByRole("button", { name: "Create account", exact: true })
      .click();
  }
  await expect(
    page.getByRole("heading", { name: "Browser test account", exact: true }),
  ).toBeVisible();
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "Browser test account", exact: true }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});

test("explains a record load failure and recovers", async ({ page }) => {
  await page.route("**/api/account", (route) =>
    route.fulfill({
      status: 503,
      json: {
        detail:
          "Records are unavailable. Check the database and migrations, then retry.",
      },
    }),
  );
  await page.goto("/#portfolio");
  await expect(page.getByRole("alert")).toContainText(
    "Records are unavailable",
  );
  await page.unroute("**/api/account");
  await page.getByRole("button", { name: "Reload account" }).click();
  await expect(page.getByRole("alert")).toBeHidden();
});

test("explains a proxy outage and recovers", async ({ page }) => {
  await page.route("**/api/account", (route) =>
    route.fulfill({ status: 502, body: "Bad Gateway" }),
  );
  await page.goto("/#portfolio");
  await expect(page.getByRole("alert")).toContainText(
    "Could not reach your records",
  );
  await page.unroute("**/api/account");
  await page.getByRole("button", { name: "Reload account" }).click();
  await expect(page.getByRole("alert")).toBeHidden();
});
