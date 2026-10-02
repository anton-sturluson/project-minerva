import { expect, test } from "@playwright/test";

test.beforeEach(async ({ request }) => {
  await request.post("/api/account", {
    data: { name: "Browser test account", base_currency: "USD" },
  });
});

test("records cash, rejects overdraft, and keeps the draft", async ({
  page,
  request,
}) => {
  const account = await (await request.get("/api/account")).json();
  const before = await (
    await request.get(`/api/accounts/${account.id}/ledger`)
  ).json();
  await page.goto("/#portfolio");
  await page.getByLabel("Entry type", { exact: true }).selectOption("deposit");
  await page.getByLabel("Cash amount", { exact: true }).fill("3.25");
  await page
    .getByRole("button", { name: "Save cash entry", exact: true })
    .click();
  await expect(
    page.getByText("Cash entry saved.", { exact: true }),
  ).toBeVisible();
  await page
    .getByLabel("Entry type", { exact: true })
    .selectOption("withdrawal");
  await page.getByLabel("Cash amount", { exact: true }).fill("999999999999999");
  await page
    .getByRole("button", { name: "Save cash entry", exact: true })
    .click();
  await expect(page.getByRole("alert")).toContainText("cash negative");
  await expect(page.getByLabel("Cash amount", { exact: true })).toHaveValue(
    "999999999999999",
  );
  await page.getByLabel("Cash amount", { exact: true }).fill("0.25");
  await page
    .getByRole("button", { name: "Save cash entry", exact: true })
    .click();
  await expect(page.getByRole("alert")).toBeHidden();
  await expect(
    page.getByText("Cash entry saved.", { exact: true }),
  ).toBeVisible();
  await page.reload();
  await expect(page.getByTestId("cash-balance")).toBeVisible();
  const after = await (
    await request.get(`/api/accounts/${account.id}/ledger`)
  ).json();
  expect(Number(after.balance)).toBe(Number(before.balance) + 3);
  expect(after.entries.length).toBe(before.entries.length + 2);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});

test("retry after a lost response does not duplicate cash", async ({
  page,
  request,
}) => {
  const account = await (await request.get("/api/account")).json();
  const url = `/api/accounts/${account.id}/ledger`;
  const before = await (await request.get(url)).json();
  await page.goto("/#portfolio");
  await page.getByLabel("Entry type", { exact: true }).selectOption("deposit");
  await page.getByLabel("Cash amount", { exact: true }).fill("0.10");
  await page.route(
    "**/cash",
    async (route) => {
      await route.fetch();
      await route.abort();
    },
    { times: 1 },
  );
  await page
    .getByRole("button", { name: "Save cash entry", exact: true })
    .click();
  await expect(page.getByRole("alert")).toBeVisible();
  await page
    .getByRole("button", { name: "Save cash entry", exact: true })
    .click();
  await expect(
    page.getByText("Cash entry saved.", { exact: true }),
  ).toBeVisible();
  const after = await (await request.get(url)).json();
  expect(after.entries.length).toBe(before.entries.length + 1);
});
