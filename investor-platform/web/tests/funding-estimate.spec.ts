import { expect, test, performance } from "./fixtures";

test("inferred portfolio defaults to no-sale wealth estimate and preserves it across periods and retries", async ({
  page,
  account,
}, testInfo) => {
  await page.clock.install({ time: new Date("2026-10-04T16:00:00Z") });
  await page.route("**/api/accounts", (route) =>
    route.fulfill({
      json: [
        {
          ...account,
          reconstruction: {
            funding_status: "inferred",
            opening_cash: "1000",
            warning: "Synthetic reconstruction",
            source_sha256: "synthetic",
            imported_trades: 1,
            skipped: [],
            opening_positions: {},
            price_discrepancies: [],
          },
        },
      ],
    }),
  );
  await page.route("**/ledger", (route) =>
    route.fulfill({
      json: {
        currency: "USD",
        balance: "200",
        holdings: [],
        entries: [
          {
            id: 1,
            kind: "buy",
            effective_date: "2024-01-02",
            amount: "1000",
            quantity: "10",
            price: "100",
            fees: "0",
            currency: "USD",
            note: "",
            security: {
              id: "00000000-0000-4000-8000-000000000003",
              ticker: "AAA",
              exchange: "NYSE",
              currency: "USD",
            },
          },
        ],
      },
    }),
  );
  let failure = false;
  const requests: {
    benchmark_mode: string;
    scope: string;
    start: string;
    baseline?: string;
  }[] = [];
  const points = [
    {
      date: "2024-01-02",
      value: "1000",
      cash: "0",
      portfolio: "0",
      SPY: "0",
      QQQ: "0",
    },
    {
      date: "2025-12-31",
      value: "1150",
      cash: "150",
      portfolio: ".15",
      SPY: ".20",
      QQQ: ".30",
    },
    {
      date: "2026-10-02",
      value: "1200",
      cash: "200",
      portfolio: ".20",
      SPY: ".30",
      QQQ: ".40",
    },
  ];
  await page.route("**/performance", (route) => {
    const body = route.request().postDataJSON();
    requests.push(body);
    if (failure)
      return route.fulfill({
        status: 503,
        json: { detail: "Synthetic price outage" },
      });
    if (body.benchmark_mode !== "funded_hold")
      return route.fulfill({
        json: {
          ...performance,
          scope: body.scope,
          benchmark_mode: body.benchmark_mode,
        },
      });
    const selected = points.filter((point) => point.date >= body.start);
    const series = selected.map((point) => ({
      ...point,
      ...Object.fromEntries(
        (["portfolio", "SPY", "QQQ"] as const).map((key) => [
          key,
          String((1 + Number(point[key])) / (1 + Number(selected[0][key])) - 1),
        ]),
      ),
    }));
    return route.fulfill({
      json: {
        ...performance,
        start: series[0].date,
        end: "2026-10-02",
        scope: "account",
        benchmark_mode: "funded_hold",
        baseline: "history",
        provisional: true,
        return: series.at(-1)!.portfolio,
        SPY: series.at(-1)!.SPY,
        QQQ: series.at(-1)!.QQQ,
        benchmark_values: { SPY: { value: "1300" }, QQQ: { value: "1400" } },
        funding_estimate: { capital: "1000", estimated_dividends: "50" },
        series,
      },
    });
  });
  await page.goto("/#performance");
  const control = page.getByLabel("Index comparison");
  const table = page.getByLabel("Performance summary", { exact: true });
  await expect(control).toHaveValue("funded_hold");
  await expect(
    page.getByRole("heading", { name: "Portfolio vs. buy & hold" }),
  ).toBeVisible();
  await expect(page.getByLabel("Performance measure")).toHaveValue("account");
  await expect(page.getByLabel("Performance measure")).toBeDisabled();
  await expect(
    table.getByRole("columnheader", { name: "Estimated value (USD)" }),
  ).toBeVisible();
  await expect(
    table.getByRole("row", { name: /Your portfolio \+ cash/ }),
  ).toContainText("1,200.00");
  await expect(table.getByRole("row", { name: /S&P 500/ })).toContainText(
    "1,300.00",
  );
  await expect(table.getByRole("row", { name: /Nasdaq-100/ })).toContainText(
    "1,400.00",
  );
  await expect(
    page.getByText(/Indexes invest each stock purchase/),
  ).toHaveCount(0);
  await expect(page.getByText(/Index gains over displayed/)).toHaveCount(0);
  await expect(
    page.getByRole("combobox", { name: "Excluded stocks" }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "YTD", exact: true }).click();
  await expect(control).toHaveValue("funded_hold");
  await expect(
    table.getByRole("row", { name: /Your portfolio \+ cash/ }),
  ).toContainText("1,200.00");
  await expect(table.getByRole("row", { name: /S&P 500/ })).toContainText(
    "1,300.00",
  );
  expect(requests.at(-1)?.baseline).toBe("recorded");
  await expect(
    page.getByRole("region", { name: "Yearly performance", exact: true }),
  ).toContainText("8.33%");
  failure = true;
  await page
    .getByRole("button", { name: "Compare performance", exact: true })
    .click();
  await expect(page.getByRole("alert")).toContainText("Synthetic price outage");
  await expect(table).toHaveCount(0);
  failure = false;
  await page
    .getByRole("button", { name: "Retry comparison", exact: true })
    .click();
  await expect(table).toBeVisible();
  await expect(control).toHaveValue("funded_hold");
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: testInfo.outputPath("funding-estimate.png"),
    fullPage: true,
  });
  await control.selectOption("buy_hold");
  await expect(page.getByLabel("Performance measure")).toBeEnabled();
  await expect(
    table.getByRole("columnheader", { name: "Estimated value (USD)" }),
  ).toHaveCount(0);
  await control.selectOption("funded_hold");
  await expect(table.getByRole("row", { name: /S&P 500/ })).toContainText(
    "1,300.00",
  );
  await page.reload();
  await expect(control).toHaveValue("funded_hold");
  await expect(
    table.getByRole("columnheader", { name: "Estimated value (USD)" }),
  ).toBeVisible();
});
