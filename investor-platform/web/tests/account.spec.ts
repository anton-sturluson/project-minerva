import { expect, test } from "./fixtures";

test("creates an account and keeps it after reload", async ({ page }) => {
  // Exercise the empty-workspace UI even when other synthetic workflows ran first.
  let created = false;
  await page.route("**/api/accounts", (route) => {
    if (route.request().method() === "POST") created = true;
    return created ? route.fallback() : route.fulfill({ json: [] });
  });
  await page.goto("/#portfolio");
  await page
    .getByLabel("Portfolio name", { exact: true })
    .fill(`Synthetic persistence ${crypto.randomUUID().slice(0, 8)}`);
  await page.getByLabel("Base currency", { exact: true }).selectOption("USD");
  await page
    .getByRole("button", { name: "Create portfolio", exact: true })
    .click();
  await expect(
    page.getByRole("combobox", { name: "Portfolio", exact: true }),
  ).toBeVisible();
  const selected = await page
    .getByLabel("Portfolio", { exact: true })
    .inputValue();
  await page.reload();
  await expect(
    page.getByRole("combobox", { name: "Portfolio", exact: true }),
  ).toBeVisible();
  await expect(page.getByLabel("Portfolio", { exact: true })).toHaveValue(
    selected,
  );
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});

test("explains a record load failure and recovers", async ({ page }) => {
  await page.route("**/api/accounts", (route) =>
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
  await page.unroute("**/api/accounts");
  await page.getByRole("button", { name: "Reload portfolios" }).click();
  await expect(page.getByRole("alert")).toBeHidden();
});

test("explains a proxy outage and recovers", async ({ page }) => {
  await page.route("**/api/accounts", (route) =>
    route.fulfill({ status: 502, body: "Bad Gateway" }),
  );
  await page.goto("/#portfolio");
  await expect(page.getByRole("alert")).toContainText(
    "Could not reach your records",
  );
  await page.unroute("**/api/accounts");
  await page.getByRole("button", { name: "Reload portfolios" }).click();
  await expect(page.getByRole("alert")).toBeHidden();
});

test("creates another portfolio, isolates activity, and remembers selection", async ({
  page,
  request,
  account,
}) => {
  const original = account;
  const originalLedger = await (
    await request.get(`/api/accounts/${original.id}/ledger`)
  ).json();
  const name = `Synthetic index ${crypto.randomUUID().slice(0, 8)}`;
  await page.goto("/#portfolio");
  await page
    .getByRole("button", { name: "New portfolio", exact: true })
    .click();
  await page.getByLabel("Portfolio name", { exact: true }).fill(name);
  await page
    .getByRole("button", { name: "Create portfolio", exact: true })
    .click();
  const select = page.getByRole("combobox", { name: "Portfolio", exact: true });
  await expect(
    select.getByRole("option", { name, exact: true }),
  ).toBeAttached();
  await expect(select).not.toHaveValue(original.id);
  const id = await select.inputValue();
  await page.getByRole("link", { name: "[ Activity ]", exact: true }).click();
  await page.getByText("Record cash", { exact: true }).click();
  await page
    .getByLabel("Entry type", { exact: true })
    .selectOption("opening_cash");
  await page.getByLabel("Cash amount", { exact: true }).fill("123");
  await page
    .getByRole("button", { name: "Save cash entry", exact: true })
    .click();
  await expect(page.getByTestId("cash-balance")).toHaveText("USD 123.00");
  await page.reload();
  await expect(select).toHaveValue(id);
  await expect(page.getByTestId("cash-balance")).toHaveText("USD 123.00");
  await select.selectOption(original.id);
  await expect(page.getByTestId("cash-balance")).not.toHaveText("USD 123.00");
  expect(
    await (await request.get(`/api/accounts/${original.id}/ledger`)).json(),
  ).toEqual(originalLedger);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});
