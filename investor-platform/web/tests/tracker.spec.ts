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
  await page.getByText("Daily values", { exact: true }).click();
  await expect(
    page.getByLabel("Daily performance", { exact: true }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.getByLabel("Performance end").fill("2026-01-06");
  await expect(
    page.getByText("Closing value (USD)", { exact: true }),
  ).toBeHidden();
  const comparison = page.waitForRequest("**/performance");
  await page.getByRole("button", { name: "Compare performance" }).click();
  expect((await comparison).postDataJSON()).toEqual({
    start: "2026-01-02",
    end: "2026-01-06",
  });
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
    await page.route("**/api/account", (route) =>
      route.fulfill({
        json: {
          id: "synthetic-account",
          name: "Synthetic comparison",
          base_currency: currency,
        },
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
  await page.goto("/");
  const holdings = page.getByLabel("Holdings", { exact: true });
  await expect(holdings).toHaveCount(1);
  await expect(holdings).toContainText("83.33%");
  const allocation = page.getByLabel("Portfolio allocation by market value");
  await expect(allocation).toContainText("16.67%");
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
  await expect(holdings).toContainText("800.00");
  await expect(allocation).toBeHidden();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});
