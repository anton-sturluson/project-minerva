import { expect, test, performance } from "./fixtures";

test("switches both indexes, retains mode across periods, and recovers from failure", async ({
  page,
}, testInfo) => {
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
            kind: "buy",
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
  const requests: {
    benchmark_mode: string;
    baseline?: string;
    scope: string;
  }[] = [];
  await page.route("**/performance", (route) => {
    const body = route.request().postDataJSON();
    requests.push(body);
    if (fail)
      return route.fulfill({
        status: 503,
        json: { detail: "Synthetic index outage" },
      });
    const matched = body.benchmark_mode === "matched";
    return route.fulfill({
      json: {
        ...performance,
        baseline: body.baseline,
        benchmark_mode: body.benchmark_mode,
        scope: body.scope,
        SPY: matched ? ".01" : ".02",
        QQQ: matched ? ".03" : ".04",
        matched_benchmarks: matched
          ? {
              SPY: { value: "1010", gain: "10", proceeds: "0" },
              QQQ: { value: "1030", gain: "30", proceeds: "0" },
            }
          : null,
        series: performance.series.map((point, index) => ({
          ...point,
          SPY: index && matched ? ".01" : point.SPY,
          QQQ: index && matched ? ".03" : point.QQQ,
        })),
      },
    });
  });
  await page.goto("/#performance");
  const control = page.getByRole("combobox", { name: "Index comparison" });
  const summary = page.getByLabel("Performance summary", { exact: true });
  const chart = page.getByRole("img", { name: /Cumulative portfolio/ });
  await expect(control).toHaveValue("buy_hold");
  await expect(summary.getByRole("row", { name: /S&P 500/ })).toContainText(
    "2.00%",
  );
  const originalSpy = await chart.locator(".spy-line").getAttribute("points");
  const originalQqq = await chart.locator(".qqq-line").getAttribute("points");
  const originalPortfolio = await chart
    .locator(".portfolio-line")
    .getAttribute("points");
  await control.selectOption("matched");
  await expect(summary.getByRole("row", { name: /S&P 500/ })).toContainText(
    "1.00%",
  );
  await expect(summary.getByRole("row", { name: /Nasdaq-100/ })).toContainText(
    "3.00%",
  );
  await expect(
    summary.getByRole("columnheader", { name: "Invested value (USD)" }),
  ).toBeVisible();
  await expect(
    summary.getByRole("row", { name: /Stock portfolio/ }),
  ).toContainText("1,200.00");
  await expect(summary.getByRole("row", { name: /S&P 500/ })).toContainText(
    "1,010.00",
  );
  await expect(summary.getByRole("row", { name: /Nasdaq-100/ })).toContainText(
    "1,030.00",
  );
  await expect(
    page.getByText(/Estimated daily time-weighted returns/),
  ).toHaveCount(0);
  await expect(
    page.getByText(/Indexes invest each stock purchase/),
  ).toHaveCount(0);
  await expect(page.getByText(/Index gains over displayed period/)).toHaveCount(
    0,
  );
  await expect(page.getByText(/Estimated · stocks only/)).toHaveCount(0);
  await expect(chart.locator(".spy-line")).not.toHaveAttribute(
    "points",
    originalSpy!,
  );
  await expect(chart.locator(".qqq-line")).not.toHaveAttribute(
    "points",
    originalQqq!,
  );
  await expect(chart.locator(".portfolio-line")).toHaveAttribute(
    "points",
    originalPortfolio!,
  );
  const yearly = page.getByRole("region", {
    name: "Yearly performance",
    exact: true,
  });
  await expect(yearly).toContainText("1.00%");
  await expect(yearly).toContainText("3.00%");
  await page.getByRole("button", { name: "YTD", exact: true }).click();
  await expect(control).toHaveValue("matched");
  await expect(
    page.getByText(/Existing holdings start at their value/),
  ).toHaveCount(0);
  await expect(summary.getByRole("row", { name: /S&P 500/ })).toContainText(
    "1,010.00",
  );
  expect(requests.at(-1)?.benchmark_mode).toBe("matched");
  expect(requests.at(-1)?.baseline).toBe("recorded");
  await page
    .getByRole("combobox", { name: "Performance measure" })
    .selectOption("account");
  await expect(summary).toBeVisible();
  await expect(
    summary.getByRole("columnheader", { name: "Invested value (USD)" }),
  ).toHaveCount(0);
  expect(requests.at(-1)?.benchmark_mode).toBe("matched");
  expect(requests.at(-1)?.scope).toBe("account");
  fail = true;
  await page
    .getByRole("button", { name: "Compare performance", exact: true })
    .click();
  await expect(
    page.getByRole("alert").filter({ hasText: "Synthetic index outage" }),
  ).toBeVisible();
  await expect(chart).toHaveCount(0);
  await expect(control).toHaveValue("matched");
  fail = false;
  await page
    .getByRole("button", { name: "Retry comparison", exact: true })
    .click();
  await expect(summary).toBeVisible();
  await page
    .getByRole("combobox", { name: "Performance measure" })
    .selectOption("stocks");
  await expect(
    summary.getByRole("columnheader", { name: "Invested value (USD)" }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: testInfo.outputPath("matched-indexes.png"),
    fullPage: true,
  });
  await control.selectOption("buy_hold");
  await expect(summary.getByRole("row", { name: /S&P 500/ })).toContainText(
    "2.00%",
  );
  await expect(
    summary.getByRole("columnheader", { name: "Invested value (USD)" }),
  ).toHaveCount(0);
  await expect(chart.locator(".spy-line")).toHaveAttribute(
    "points",
    originalSpy!,
  );
  await expect(chart.locator(".qqq-line")).toHaveAttribute(
    "points",
    originalQqq!,
  );
});
