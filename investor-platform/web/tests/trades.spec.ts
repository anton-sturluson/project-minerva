import { expect, test } from "./fixtures";

test("opening shares, buy, partial sale, oversell rejection, close and reload", async ({
  page,
  request,
}, info) => {
  await request.post("/api/accounts", {
    data: { name: "Browser test account", base_currency: "USD" },
  });
  const account = (await (await request.get("/api/accounts")).json())[0];
  await request.post(`/api/accounts/${account.id}/cash`, {
    data: {
      kind: "deposit",
      amount: "1000",
      currency: "USD",
      effective_date: new Date().toISOString().slice(0, 10),
      request_key: crypto.randomUUID(),
    },
  });
  const before = await (
    await request.get(`/api/accounts/${account.id}/ledger`)
  ).json();
  const ticker = `T${Date.now()}${info.project.name === "mobile" ? "M" : "D"}`;
  await page.goto("/#activity");
  await page.getByText("Record a position or trade", { exact: true }).click();
  await page
    .getByLabel("Position action", { exact: true })
    .selectOption("opening_position");
  await page.getByLabel("Ticker", { exact: true }).fill(ticker);
  await page.getByLabel("Exchange", { exact: true }).fill("TEST");
  await page.getByLabel("Shares", { exact: true }).fill("3");
  await page
    .getByRole("button", { name: "Save position entry", exact: true })
    .click();
  await expect(
    page.getByText("Position entry saved.", { exact: true }),
  ).toBeVisible();
  async function holding() {
    const latest = await (
      await request.get(`/api/accounts/${account.id}/ledger`)
    ).json();
    return latest.holdings.find(
      (h: { security: { ticker: string } }) => h.security.ticker === ticker,
    );
  }
  expect((await holding()).cost_basis).toBeNull();
  await page.getByLabel("Position action", { exact: true }).selectOption("buy");
  await page.getByLabel("Shares", { exact: true }).fill("2");
  await page.getByLabel("Price per share", { exact: true }).fill("10");
  await page.getByLabel("Trade fees", { exact: true }).fill("1");
  // Lose the server's response after commit, then retry the unchanged draft.
  await page.route(
    "**/trades",
    async (route) => {
      await route.fetch();
      await route.abort();
    },
    { times: 1 },
  );
  await page
    .getByRole("button", { name: "Save position entry", exact: true })
    .click();
  await expect(page.getByRole("alert")).toBeVisible();
  await page
    .getByRole("button", { name: "Save position entry", exact: true })
    .click();
  await expect(page.getByRole("alert")).toBeHidden();
  expect(Number((await holding()).quantity)).toBe(5);
  await page
    .getByLabel("Position action", { exact: true })
    .selectOption("sell");
  await page.getByLabel("Shares", { exact: true }).fill("99");
  await page
    .getByRole("button", { name: "Save position entry", exact: true })
    .click();
  await expect(page.getByRole("alert")).toContainText("negative shares");
  await expect(page.getByLabel("Shares", { exact: true })).toHaveValue("99");
  await page.getByLabel("Shares", { exact: true }).fill("4");
  await page.getByLabel("Price per share", { exact: true }).fill("20");
  await page
    .getByRole("button", { name: "Save position entry", exact: true })
    .click();
  await expect(page.getByRole("alert")).toBeHidden();
  expect(Number((await holding()).cost_basis)).toBe(10.5);
  await page.getByText("Account activity", { exact: true }).click();
  const sale = page.getByRole("row").filter({ hasText: `Sell · ${ticker}` });
  await sale.locator("summary").click();
  await expect(sale).toContainText("Unknown: opening basis unavailable");
  await page.getByLabel("Shares", { exact: true }).fill("1");
  await page
    .getByRole("button", { name: "Save position entry", exact: true })
    .click();
  await expect(page.getByLabel("Shares", { exact: true })).toHaveValue("");
  expect(await holding()).toBeUndefined();
  await page.reload();
  await expect(page.getByTestId("cash-balance")).toBeVisible();
  const after = await (
    await request.get(`/api/accounts/${account.id}/ledger`)
  ).json();
  expect(Number(after.balance)).toBe(Number(before.balance) + 77);
  expect(after.entries.length).toBe(before.entries.length + 4);
  expect(
    after.holdings.some(
      (h: { security: { ticker: string } }) => h.security.ticker === ticker,
    ),
  ).toBe(false);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});
