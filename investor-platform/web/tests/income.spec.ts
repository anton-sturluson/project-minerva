import { expect, test } from "./fixtures";

test("records a dividend payment and preserves attribution through correction", async ({
  page,
  request,
}) => {
  const name = `Synthetic income ${crypto.randomUUID().slice(0, 8)}`;
  const account = await (
    await request.post("/api/accounts", {
      data: { name, base_currency: "USD" },
    })
  ).json();
  const base = `/api/accounts/${account.id}`;
  await request.post(base + "/cash", {
    data: {
      request_key: crypto.randomUUID(),
      kind: "opening_cash",
      amount: "1000",
      currency: "USD",
      effective_date: "2026-01-02",
    },
  });
  const buy = await (
    await request.post(base + "/trades", {
      data: {
        request_key: crypto.randomUUID(),
        kind: "buy",
        ticker: "AAA",
        exchange: "NYSE",
        quantity: "10",
        price: "100",
        currency: "USD",
        effective_date: "2026-01-02",
      },
    })
  ).json();
  await page.goto("/#activity");
  await page
    .getByRole("combobox", { name: "Portfolio", exact: true })
    .selectOption(account.id);
  await page.getByText("Record cash", { exact: true }).click();
  await page.getByLabel("Entry type", { exact: true }).selectOption("income");
  await page
    .getByLabel("Income type", { exact: true })
    .selectOption("dividend");
  await page
    .getByLabel("Dividend security", { exact: true })
    .selectOption(buy.security.id);
  await page
    .getByLabel("Cash effective date", { exact: true })
    .fill("2026-01-08");
  await page.getByLabel("Ex-dividend date", { exact: true }).fill("2026-01-05");
  await page.getByLabel("Cash amount", { exact: true }).fill("10");
  await page
    .getByRole("button", { name: "Save cash entry", exact: true })
    .click();
  await expect(page.getByTestId("cash-balance")).toHaveText("USD 10.00");
  const ledger = await (await request.get(base + "/ledger")).json();
  const dividend = ledger.entries.find(
    (e: { income_kind: string }) => e.income_kind === "dividend",
  );
  expect(dividend.income_security.id).toBe(buy.security.id);
  expect(dividend.accrual_date).toBe("2026-01-05");
  await page.getByText("Account activity", { exact: true }).click();
  await expect(
    page.getByRole("row").filter({ hasText: "dividend" }),
  ).toContainText("ex 2026-01-05");
  await page
    .getByRole("button", { name: `Correct entry ${dividend.id}`, exact: true })
    .click();
  await expect(
    page
      .getByRole("group", { name: "Correction", exact: true })
      .getByLabel("Income type", { exact: true }),
  ).toHaveValue("dividend");
  await expect(
    page
      .getByRole("group", { name: "Correction", exact: true })
      .getByLabel("Dividend security", { exact: true }),
  ).toHaveValue(buy.security.id);
  await page.getByLabel("Replacement cash amount", { exact: true }).fill("12");
  await page
    .getByLabel("Correction reason", { exact: true })
    .fill("Synthetic gross amount correction");
  await page
    .getByRole("button", { name: "Preview correction", exact: true })
    .click();
  await expect(page.getByLabel("Correction preview")).toContainText(
    "ex 2026-01-05",
  );
  await page
    .getByRole("button", { name: "Confirm correction", exact: true })
    .click();
  await expect(page.getByTestId("cash-balance")).toHaveText("USD 12.00");
  await page.reload();
  await expect(page.getByTestId("cash-balance")).toHaveText("USD 12.00");
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});
