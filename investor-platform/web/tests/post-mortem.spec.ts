import { expect, test, performance } from "./fixtures";

const rows = [
  {
    security_id: "a",
    ticker: "AAA",
    exchange: "NYSE",
    contribution: ".15",
    gain: "150",
  },
  {
    security_id: "b",
    ticker: "BBB",
    exchange: "NASDAQ",
    contribution: "-.05",
    gain: "1000",
  },
  {
    security_id: "c",
    ticker: "CCC",
    exchange: "NYSE",
    contribution: ".02",
    gain: "-500",
  },
];
const period = {
  period: "2025",
  start: "2024-12-31",
  end: "2025-12-31",
  return: ".12",
  contribution_total: ".12",
  gain: "650",
  stocks: rows,
};

test("post-mortem ranks contributions, switches years, recovers and isolates accounts", async ({
  page,
}) => {
  let empty = false;
  await page.route("**/ledger", (route) =>
    route.fulfill({
      json: {
        currency: "USD",
        balance: "0",
        holdings: [],
        entries: empty
          ? []
          : [
              {
                id: 1,
                kind: "opening_cash",
                effective_date: "2024-01-02",
                amount: "1000",
                currency: "USD",
                note: "",
                security: null,
              },
            ],
      },
    }),
  );
  let fail = false;
  await page.route("**/performance", (route) =>
    fail
      ? route.fulfill({
          status: 503,
          json: { detail: "Synthetic history unavailable" },
        })
      : route.fulfill({
          json: {
            ...performance,
            attribution: [
              { ...period, period: "all" },
              {
                ...period,
                period: "2024",
                start: "2024-01-02",
                end: "2024-12-31",
                return: null,
                contribution_total: null,
                gain: "150",
                stocks: [{ ...rows[0], contribution: null }],
              },
              period,
            ],
          },
        }),
  );
  await page.goto("/#post-mortem");
  await expect(
    page.getByRole("heading", { name: "Post-mortem", exact: true }),
  ).toBeVisible();
  const analysis = page.getByRole("region", {
    name: "Stock contribution analysis",
    exact: true,
  });
  await expect(
    page.getByRole("region", { name: "Main contributors", exact: true }),
  ).toContainText("AAA");
  await expect(
    page.getByRole("region", { name: "Main detractors", exact: true }),
  ).toContainText("BBB");
  const table = page.getByLabel("Stock contributions", { exact: true });
  await expect(table.getByRole("row", { name: /^Total/ })).toContainText(
    "+12.00 pp",
  );
  await expect(table.getByRole("row", { name: /^BBB/ })).toContainText(
    "-5.00 pp",
  );
  await expect(page.getByLabel("Holdings", { exact: true })).toBeHidden();
  await page.getByLabel("Post-mortem year").selectOption("2024");
  await expect(analysis).toContainText("Unavailable for this period.");
  const measure = page.getByLabel("Post-mortem measure");
  await measure.selectOption("gain");
  await expect(table).toContainText("+$150.0");
  await expect(analysis).not.toContainText("Unavailable for this period.");
  await page.getByLabel("Post-mortem year").selectOption("all");
  await expect(measure).toHaveValue("gain");
  await expect(table.locator("tbody tr").first()).toContainText("BBB");
  await expect(table.getByRole("row", { name: /^Total/ })).toContainText(
    "+$650.0",
  );
  await expect(
    page
      .getByRole("region", { name: "Main contributors", exact: true })
      .locator("li")
      .first(),
  ).toContainText("BBB");
  await expect(
    page.getByRole("region", { name: "Main detractors", exact: true }),
  ).toContainText("CCC");
  await expect(table).not.toContainText("pp");
  await measure.selectOption("contribution");
  await expect(table.locator("tbody tr").first()).toContainText("AAA");
  await expect(table.getByRole("row", { name: /^Total/ })).toContainText(
    "+12.00 pp",
  );
  await page.getByLabel("Post-mortem year").selectOption("2025");
  await expect(measure).toHaveValue("contribution");
  await page.getByLabel("Post-mortem year").selectOption("all");
  await expect(measure).toHaveValue("gain");
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.getByRole("link", { name: "[ Portfolio ]", exact: true }).click();
  fail = true;
  await page
    .getByRole("link", { name: "[ Post-mortem ]", exact: true })
    .click();
  await expect(analysis.getByRole("alert")).toContainText(
    "Synthetic history unavailable",
  );
  await expect(table).toBeHidden();
  fail = false;
  await page
    .getByRole("button", { name: "Retry post-mortem", exact: true })
    .click();
  await expect(table).toContainText("+15.00 pp");
  const original = await page
    .getByLabel("Portfolio", { exact: true })
    .inputValue();
  empty = true;
  await page
    .getByRole("button", { name: "New portfolio", exact: true })
    .click();
  await page
    .getByLabel("Portfolio name", { exact: true })
    .fill(`Synthetic attribution ${crypto.randomUUID().slice(0, 8)}`);
  await page
    .getByRole("button", { name: "Create portfolio", exact: true })
    .click();
  await expect(page.getByLabel("Portfolio", { exact: true })).not.toHaveValue(
    original,
  );
  await expect(table).toBeHidden();
  await expect(analysis).toContainText("No stock history yet.");
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});
