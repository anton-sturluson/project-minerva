import { expect, test, performance } from "./fixtures";

const dates = [
  "2024-07-01",
  "2024-12-31",
  "2025-01-02",
  "2025-12-31",
  "2026-01-02",
  "2026-10-02",
];
const portfolio = ["0", ".20", ".26", ".50", ".40", ".35"];
const spy = ["0", ".10", ".11", ".32", ".40", ".452"];
const qqq = ["0", ".30", ".32", ".82", ".90", "1.184"];
const series = dates.map((date, index) => ({
  date,
  portfolio: portfolio[index],
  SPY: spy[index],
  QQQ: qqq[index],
  value: "1000",
  cash: "0",
}));

test("yearly returns use prior year-end, distinguish partial periods and sign benchmark differences", async ({
  page,
}) => {
  await page.clock.install({ time: new Date("2026-10-04T16:00:00Z") });
  await page.route("**/ledger", (route) =>
    route.fulfill({
      json: {
        currency: "USD",
        balance: "0",
        holdings: [],
        entries: [
          {
            id: 1,
            kind: "opening_cash",
            effective_date: dates[0],
            amount: "1000",
            currency: "USD",
            note: "",
            security: null,
          },
        ],
      },
    }),
  );
  let missing = false;
  await page.route("**/performance", (route) =>
    route.fulfill({
      json: {
        ...performance,
        scope: "stocks",
        start: dates[0],
        end: dates.at(-1),
        return: missing ? null : ".35",
        series: series.map((p) => ({
          ...p,
          portfolio: missing ? null : p.portfolio,
        })),
        warnings: missing ? ["Synthetic missing income"] : [],
      },
    }),
  );
  await page.goto("/#performance");
  const table = page.getByRole("region", {
    name: "Yearly performance",
    exact: true,
  });
  const year2025 = table.getByRole("row", { name: /^2025/ });
  // 1.50 / 1.20 - 1 = 25%, not the 30-point difference or a Jan-2 baseline.
  await expect(year2025).toContainText("25.00%");
  await expect(year2025).toContainText("20.00%");
  await expect(year2025).toContainText("40.00%");
  await expect(
    year2025.getByLabel("Portfolio minus S&P 500", { exact: true }),
  ).toHaveText("+5.00 pp");
  await expect(
    year2025.getByLabel("Portfolio minus S&P 500", { exact: true }),
  ).toHaveClass(/gain/);
  await expect(
    year2025.getByLabel("Portfolio minus Nasdaq-100", { exact: true }),
  ).toHaveText("-15.00 pp");
  await expect(
    year2025.getByLabel("Portfolio minus Nasdaq-100", { exact: true }),
  ).toHaveClass(/loss/);
  await expect(table.getByRole("row", { name: /^2024/ })).toContainText(
    "partial",
  );
  await expect(table.getByRole("row", { name: /^2026/ })).toContainText("YTD");
  await expect(table.getByRole("row", { name: /^2026/ })).toContainText(
    "-10.00%",
  );
  await expect(table.getByRole("row", { name: /^2026/ })).toContainText(
    "-20.00 pp",
  );
  missing = true;
  await page
    .getByRole("button", { name: "Compare performance", exact: true })
    .click();
  await expect(year2025.getByRole("cell").first()).toHaveText("—");
  await expect(
    year2025.getByLabel("Portfolio minus S&P 500", { exact: true }),
  ).toHaveText("—");
  await expect(year2025).toContainText("20.00%");
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});
