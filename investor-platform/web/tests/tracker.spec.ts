import { expect, test, performance } from "./fixtures";

const ledger = {
  currency: "USD",
  balance: "1000",
  holdings: [],
  entries: [
    {
      id: 1,
      kind: "opening_cash",
      effective_date: "2026-01-02",
      amount: "1000",
      currency: "USD",
      note: "Synthetic fixture",
      created_at: "2026-01-02T12:00:00Z",
      security: null,
    },
  ],
};

test("compares dated returns, explains outage, and invalidates old results", async ({
  page,
}) => {
  // Fixed market response keeps CI independent of Yahoo availability; real feed tested manually.
  let fail = false;
  await page.route("**/api/accounts/*/ledger", (route) =>
    route.fulfill({
      json: ledger,
    }),
  );
  await page.route("**/api/accounts/*/performance", (route) =>
    fail
      ? route.fulfill({
          status: 503,
          json: { detail: "Market data is unavailable. Retry the comparison." },
        })
      : route.fulfill({
          json: performance,
        }),
  );
  await page.route("**/statistics", (route) =>
    route.fulfill({
      status: 503,
      json: { detail: "Scorecard temporarily unavailable." },
    }),
  );
  await page.goto("/");
  await expect(
    page.getByRole("button", { name: "Retry scorecard" }),
  ).toBeVisible();
  // The index report appears without a button click, even when the scorecard fails.
  await page
    .getByRole("link", { name: "[ Performance ]", exact: true })
    .click();
  await expect(
    page.getByText("Closing value (USD)", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("img", { name: /Cumulative portfolio/ }),
  ).toBeVisible();
  // Retrying the independent scorecard must preserve a successful comparison.
  await page.unroute("**/statistics");
  await page.getByRole("button", { name: "Retry scorecard" }).click();
  await expect(page.getByTestId("win-rate")).toBeVisible();
  await expect(
    page.getByText("Closing value (USD)", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText("Daily values", { exact: true })).toHaveCount(0);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.getByLabel("Performance end").fill("2026-01-06");
  await expect(
    page.getByText("Closing value (USD)", { exact: true }),
  ).toBeHidden();
  await page.getByLabel("Performance measure").selectOption("account");
  await expect(
    page.getByRole("button", { name: "Compare performance" }),
  ).toBeEnabled();
  const comparison = page.waitForRequest("**/performance");
  await page.getByRole("button", { name: "Compare performance" }).click();
  expect((await comparison).postDataJSON()).toEqual({
    scope: "account",
    start: "2026-01-02",
    end: "2026-01-06",
  });
  await expect(
    page.getByText("Closing value (USD)", { exact: true }),
  ).toBeVisible();
  await page.getByLabel("Performance start").fill("2026-01-05");
  const custom = page.waitForRequest("**/performance");
  await page.getByRole("button", { name: "Compare performance" }).click();
  expect((await custom).postDataJSON()).toEqual({
    scope: "account",
    start: "2026-01-05",
    end: "2026-01-06",
    baseline: "recorded",
  });

  const full = page.waitForRequest("**/performance");
  await page.getByRole("button", { name: "Full history", exact: true }).click();
  expect((await full).postDataJSON().baseline).toBeUndefined();
  await expect(
    page.getByText("Closing value (USD)", { exact: true }),
  ).toBeVisible();
  fail = true;
  await page.getByRole("button", { name: "Compare performance" }).click();
  await expect(page.getByRole("alert")).toContainText(
    "Market data is unavailable",
  );
  await expect(
    page.getByText("Closing value (USD)", { exact: true }),
  ).toBeHidden();
  fail = false;
  await page.getByRole("button", { name: "Retry comparison" }).click();
  await expect(
    page.getByText("Closing value (USD)", { exact: true }),
  ).toBeVisible();
});

test("a ledger save reloads the comparison and ignores a late previous report", async ({
  page,
}) => {
  await page.route("**/ledger", (route) => route.fulfill({ json: ledger }));
  let saved = false;
  await page.route("**/cash", (route) => {
    saved = true;
    return route.fulfill({ json: {} });
  });
  let release!: () => void;
  const pending = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route("**/performance", async (route) => {
    const first = !saved;
    if (first) await pending;
    await route.fulfill({
      json: { ...performance, value: first ? "1200" : "1300" },
    });
  });
  await page.goto("/");
  await expect(page.getByRole("status")).toContainText(
    "Loading portfolio and index returns",
  );
  // Records remain usable while the market provider is slow.
  await page.getByRole("link", { name: "[ Activity ]", exact: true }).click();
  await page.getByText("Record cash", { exact: true }).click();
  await page.getByLabel("Cash amount").fill("100");
  await page.getByRole("button", { name: "Save cash entry" }).click();
  await page.getByRole("link", { name: "[ Portfolio ]", exact: true }).click();
  await expect(page.getByText("1,300.00", { exact: true })).toBeVisible();
  const lateResponse = page.waitForResponse("**/performance");
  release();
  await lateResponse;
  await expect(page.getByText("1,300.00", { exact: true })).toBeVisible();
  await expect(page.getByText("1,200.00", { exact: true })).toBeHidden();
});

for (const currency of ["USD", "EUR"]) {
  test(`explains unavailable comparison for ${currency === "USD" ? "empty history" : "unsupported currency"}`, async ({
    page,
  }) => {
    await page.route("**/api/accounts", (route) =>
      route.fulfill({
        json: [
          {
            id: "synthetic-account",
            name: "Synthetic comparison",
            base_currency: currency,
          },
        ],
      }),
    );
    await page.route("**/ledger", (route) =>
      route.fulfill({
        json: {
          ...ledger,
          currency,
          entries: currency === "USD" ? [] : ledger.entries,
        },
      }),
    );
    // Statistics aren't part of this fixture's database account.
    await page.route("**/statistics", (route) =>
      route.fulfill({
        json: {
          closed: 0,
          open: 0,
          unknown: 0,
          wins: 0,
          losses: 0,
          breakeven: 0,
          win_rate: null,
          average_win: null,
          average_loss: null,
          payoff_ratio: null,
          episodes: [],
        },
      }),
    );
    let calls = 0;
    await page.route("**/performance", (route) => {
      calls++;
      return route.fulfill({ json: performance });
    });
    await page.goto("/");
    await expect(
      page.getByRole("button", { name: "Compare performance" }),
    ).toBeDisabled();
    await expect(
      page.getByText(
        currency === "USD"
          ? /A comparison needs at least two/
          : /Index comparisons currently support USD/,
      ),
    ).toBeVisible();
    await expect(
      page.getByText("Closing value (USD)", { exact: true }),
    ).toBeHidden();
    expect(calls).toBe(0);
  });
}

test("shows one holdings table above returns and retains recorded positions during quote failure", async ({
  page,
}) => {
  await page.route("**/ledger", (route) =>
    route.fulfill({
      json: {
        ...ledger,
        holdings: [
          {
            security: {
              id: "aaa",
              ticker: "AAA",
              exchange: "NYSE",
              currency: "USD",
            },
            quantity: "10",
            cost_basis: "800",
          },
        ],
      },
    }),
  );
  await page.route("**/valuation", (route) =>
    route.fulfill({
      json: {
        ...performance,
        complete: true,
        holdings: performance.holdings.map((h) => ({
          ...h,
          basis: "800",
          unrealized_pnl: "200",
        })),
      },
    }),
  );
  await page.goto("/");
  const holdings = page.getByLabel("Holdings", { exact: true });
  await expect(holdings).toHaveCount(1);
  await expect(holdings).toContainText("83.3%");
  await expect(
    page.getByLabel("Portfolio allocation by market value"),
  ).toHaveCount(0);
  const total = holdings.getByRole("row", { name: /^Stocks total/ });
  await expect(total).toContainText("1,000.0");
  await expect(total).toContainText("800.0");
  await expect(total).toContainText("+200.0 (25.0%)");
  await expect(
    holdings.getByRole("columnheader", { name: "Gain %", exact: true }),
  ).toHaveCount(0);
  await expect(
    holdings.getByRole("columnheader", { name: "Basis (USD)", exact: true }),
  ).toBeVisible();
  await expect(
    holdings.getByRole("row", { name: /^AAA/ }).getByRole("cell").first(),
  ).toHaveText("10.0");
  await expect(
    holdings.getByRole("row").filter({ hasText: "AAA" }),
  ).toContainText("80.0%");
  await page.getByLabel("Theme", { exact: true }).selectOption("dark");
  await expect(
    holdings.getByRole("columnheader", { name: "Cost %", exact: true }),
  ).toBeVisible();
  const score = await page.getByTestId("payoff-ratio").boundingBox();
  const table = await holdings.boundingBox();
  const plot = await page
    .getByRole("img", { name: /Cumulative portfolio/ })
    .boundingBox();
  expect(score!.y).toBeLessThan(table!.y);
  expect(table!.y).toBeLessThan(plot!.y);
  await page.route("**/performance", (route) =>
    route.fulfill({ status: 503, json: { detail: "Synthetic quote outage" } }),
  );
  await page.getByRole("button", { name: "Compare performance" }).click();
  await expect(page.getByRole("alert")).toContainText("Synthetic quote outage");
  await expect(total).toContainText("25.0%");
  await page.route("**/valuation", (route) =>
    route.fulfill({
      status: 503,
      json: { detail: "Synthetic holdings outage" },
    }),
  );
  await page
    .getByRole("button", { name: "Refresh prices", exact: true })
    .click();
  await expect(holdings).toContainText("800.0");
  await expect(
    holdings.getByRole("row").filter({ hasText: "AAA" }),
  ).toContainText("44.4%");
  await expect(total).toContainText("800.0");
  await expect(total).not.toContainText("25.0%");
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});

test("withholds all cost weights when any position has unknown basis", async ({
  page,
}) => {
  await page.route("**/ledger", (route) => route.fulfill({ json: ledger }));
  await page.goto("/");
  await expect(page.getByLabel("Holdings", { exact: true })).toContainText(
    "AAA",
  );
  await expect(
    page.getByText("Unknown basis · cost totals unavailable.", { exact: true }),
  ).toBeVisible();
  const total = page
    .getByLabel("Holdings", { exact: true })
    .getByRole("row", { name: /^Stocks total/ });
  await expect(total).toContainText("1,000.0");
  await expect(total.getByRole("cell").nth(5)).toHaveText("—");
  await expect(total.getByRole("cell").nth(6)).toHaveText("—");
});

test("partial holdings quotes remain visible and retry restores complete totals", async ({
  page,
}) => {
  let partial = true;
  await page.route("**/ledger", (route) => route.fulfill({ json: ledger }));
  await page.route("**/valuation", (route) =>
    route.fulfill({
      json: {
        ...performance,
        complete: !partial,
        value: partial ? null : "1200",
        holdings: [
          {
            ...performance.holdings[0],
            basis: "800",
            weight: partial ? null : "0.8333333",
          },
          ...(partial
            ? [
                {
                  ticker: "BBB",
                  exchange: "NASDAQ",
                  quantity: "2",
                  basis: "100",
                  close: null,
                  value: null,
                  weight: null,
                  unrealized_pnl: null,
                  price_error: "Close unavailable",
                },
              ]
            : []),
        ],
      },
    }),
  );
  await page.goto("/");
  const holdings = page.getByLabel("Holdings", { exact: true });
  await expect(
    holdings.getByRole("row").filter({ hasText: "AAA" }),
  ).toContainText("1,000.0");
  await expect(
    holdings.getByRole("row").filter({ hasText: "BBB" }),
  ).toContainText("Quote unavailable");
  await expect(
    page.getByLabel("Portfolio allocation by market value"),
  ).toBeHidden();
  await expect(
    page.getByText("Missing prices · totals unavailable.", { exact: true }),
  ).toBeVisible();
  partial = false;
  await page
    .getByRole("button", { name: "Refresh prices", exact: true })
    .click();
  await expect(
    holdings.getByRole("row", { name: /^Stocks total/ }),
  ).toContainText("1,000.0");
  await expect(holdings).toContainText("83.3%");
  await expect(
    page.getByText("Quote unavailable", { exact: true }),
  ).toHaveCount(0);
});

test("YTD and one-year request prior-close boundaries and preserve the measurement", async ({
  page,
}) => {
  await page.clock.install({ time: new Date("2026-10-04T16:00:00Z") });
  await page.route("**/ledger", (route) =>
    route.fulfill({
      json: {
        ...ledger,
        entries: [{ ...ledger.entries[0], effective_date: "2020-04-02" }],
      },
    }),
  );
  await page.route("**/performance", (route) => {
    const request = route.request().postDataJSON();
    return route.fulfill({
      json: {
        ...performance,
        start: request.anchor_date ?? request.start,
        end: request.end,
      },
    });
  });
  await page.goto("/");
  // Finish the initial full-history report before observing a shortcut request.
  await expect(page.getByLabel("Performance summary")).toBeVisible();
  await expect(
    page.getByRole("button", { name: "YTD", exact: true }),
  ).toBeEnabled();
  let request = page.waitForRequest("**/performance");
  await page.getByRole("button", { name: "YTD", exact: true }).click();
  expect((await request).postDataJSON()).toMatchObject({
    scope: "stocks",
    anchor_date: "2025-12-31",
    baseline: "recorded",
  });
  await expect(page.getByLabel("Performance start")).toHaveValue("2025-12-31");
  request = page.waitForRequest("**/performance");
  await page.getByRole("button", { name: "1 year", exact: true }).click();
  expect((await request).postDataJSON()).toMatchObject({
    anchor_date: "2025-10-03",
  });
  await expect(page.getByLabel("Performance start")).toHaveValue("2025-10-03");
  await page.getByRole("button", { name: "Full history", exact: true }).click();
  await expect(page.getByLabel("Performance start")).toHaveValue("2020-04-02");
});

test("chart dates label every year and adapt to shorter periods", async ({
  page,
}) => {
  await page.route("**/ledger", (route) => route.fulfill({ json: ledger }));
  let dates = [
    "2020-04-02",
    "2021-01-04",
    "2022-01-03",
    "2023-01-03",
    "2024-01-02",
    "2025-01-02",
    "2026-01-02",
    "2026-10-02",
  ];
  await page.route("**/performance", (route) =>
    route.fulfill({
      json: {
        ...performance,
        start: dates[0],
        end: dates.at(-1),
        series: dates.map((date, index) => ({
          ...performance.series[0],
          date,
          portfolio: String(index / 100),
        })),
      },
    }),
  );
  await page.goto("/#performance");
  const chart = page.getByRole("img", { name: /Cumulative portfolio/ });
  await expect(chart.getByText("2020-04-02", { exact: true })).toBeVisible();
  for (const year of ["2021", "2022", "2023", "2024", "2025", "2026"]) {
    await expect(chart.getByText(year, { exact: true })).toBeVisible();
  }
  await expect(chart.getByText("2026-10-02", { exact: true })).toBeVisible();
  dates = ["2026-01-02", "2026-04-01", "2026-07-01", "2026-10-02"];
  await page
    .getByRole("button", { name: "Compare performance", exact: true })
    .click();
  await expect(chart.getByText("Apr 26", { exact: true })).toBeVisible();
  await expect(chart.getByText("Jul 26", { exact: true })).toBeVisible();
  await expect(page.getByText("Daily values", { exact: true })).toHaveCount(0);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});

test("performance and post-mortem include today only after 5pm Eastern", async ({
  page,
}) => {
  await page.route("**/ledger", (route) => route.fulfill({ json: ledger }));
  for (const [time, end] of [
    ["2026-07-06T20:59:00Z", "2026-07-05"],
    ["2026-07-06T21:00:00Z", "2026-07-06"],
    ["2026-01-06T21:59:00Z", "2026-01-05"],
    ["2026-01-06T22:00:00Z", "2026-01-06"],
  ]) {
    await page.goto("about:blank");
    await page.clock.setFixedTime(new Date(time));
    const request = page.waitForRequest("**/performance");
    await page.goto("/#performance");
    expect((await request).postDataJSON().end).toBe(end);
    await expect(page.getByLabel("Performance end")).toHaveValue(end);
    const postMortem = page.waitForRequest("**/performance");
    await page
      .getByRole("link", { name: "[ Post-mortem ]", exact: true })
      .click();
    expect((await postMortem).postDataJSON().end).toBe(end);
  }
});
