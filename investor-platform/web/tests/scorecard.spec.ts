import { expect, test } from "./fixtures";

test("shows a closed synthetic trade and recovers a scorecard load failure", async ({
  page,
  request,
}) => {
  const account = (await (await request.get("/api/accounts")).json())[0];
  const base = `/api/accounts/${account.id}`;
  const date = new Date().toISOString().slice(0, 10);
  const ticker = `S${crypto.randomUUID().slice(0, 8).toUpperCase()}`;
  const cash = await request.post(`${base}/cash`, {
    data: {
      kind: "deposit",
      amount: "100",
      effective_date: date,
      currency: "USD",
      request_key: crypto.randomUUID(),
    },
  });
  expect(cash.ok()).toBe(true);
  for (const [kind, price] of [
    ["buy", "20"],
    ["sell", "30"],
  ]) {
    const result = await request.post(`${base}/trades`, {
      data: {
        kind,
        price,
        quantity: "1",
        ticker,
        exchange: "TEST",
        currency: "USD",
        effective_date: date,
        request_key: crypto.randomUUID(),
      },
    });
    expect(result.ok()).toBe(true);
  }
  await page.route("**/statistics", (route) =>
    route.fulfill({
      status: 503,
      json: { detail: "Scorecard temporarily unavailable." },
    }),
  );
  await page.goto("/");
  await expect(page.getByRole("alert")).toContainText(
    "Scorecard temporarily unavailable",
  );
  await page.unroute("**/statistics");
  await page.getByRole("button", { name: "Retry scorecard" }).click();
  await expect(page.getByTestId("win-rate")).toBeVisible();
  await expect(page.getByRole("alert")).toBeHidden();
  await page.getByText("Closed positions", { exact: true }).click();
  await expect(
    page
      .getByLabel("Closed positions", { exact: true })
      .getByRole("row")
      .filter({ hasText: ticker }),
  ).toContainText("10.00");
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});

test("distinguishes unconfirmed exchanges from unknown cost basis", async ({
  page,
}) => {
  await page.route("**/statistics", (route) =>
    route.fulfill({
      json: {
        closed: 2,
        open: 0,
        unknown: 1,
        wins: 1,
        losses: 0,
        breakeven: 0,
        win_rate: "1",
        payoff_ratio: null,
        average_win: "10",
        average_loss: null,
        episodes: [
          {
            ticker: "SYNTH",
            exchange: "UNVERIFIED",
            closed_on: "2026-01-06",
            pnl: "10",
          },
          {
            ticker: "OPENING",
            exchange: "NYSE",
            closed_on: "2026-01-06",
            pnl: null,
          },
        ],
      },
    }),
  );
  await page.goto("/");
  await page.getByText("Closed positions", { exact: true }).click();
  const table = page.getByLabel("Closed positions", { exact: true });
  await expect(
    table.getByRole("row").filter({ hasText: "SYNTH" }),
  ).toContainText("Exchange unconfirmed");
  await expect(
    table.getByRole("row").filter({ hasText: "SYNTH" }),
  ).toContainText("10.00");
  await expect(
    table.getByRole("row").filter({ hasText: "OPENING" }),
  ).toContainText("Unknown basis");
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});

test("toggles hypothetical closes, explains unavailable quotes and recovers", async ({
  page,
}) => {
  const actual = {
    closed: 1,
    open: 1,
    unknown: 0,
    wins: 1,
    losses: 0,
    breakeven: 0,
    win_rate: "1",
    payoff_ratio: null,
    average_win: "10",
    average_loss: null,
    episodes: [],
  };
  let fail = false;
  await page.route("**/statistics", (route) => route.fulfill({ json: actual }));
  await page.route("**/statistics/hypothetical", (route) =>
    fail
      ? route.fulfill({
          status: 503,
          json: { detail: "Latest prices unavailable for: SYNTH" },
        })
      : route.fulfill({
          json: {
            ...actual,
            closed: 2,
            open: 0,
            losses: 1,
            win_rate: "0.5",
            payoff_ratio: "2",
            average_loss: "5",
            simulated_positions: 1,
            quote_start: "2026-01-06",
            quote_end: "2026-01-06",
            episodes: [
              {
                ticker: "SYNTH",
                exchange: "NYSE",
                pnl: "-5",
                closed_on: "2026-01-07",
                hypothetical: true,
              },
            ],
          },
        }),
  );
  await page.goto("/");
  await expect(page.getByTestId("win-rate")).toHaveText("100.00%");
  const toggle = page.getByRole("checkbox", {
    name: "Hypothetical: close all open positions",
  });
  await toggle.check();
  await expect(page.getByTestId("win-rate")).toHaveText("50.00%");
  await expect(page.getByTestId("payoff-ratio")).toHaveText("2.00×");
  await expect(page.getByText(/before selling fees and taxes/)).toBeVisible();
  await page
    .getByText("Closed + hypothetical positions", { exact: true })
    .click();
  await expect(
    page
      .getByLabel("Closed positions", { exact: true })
      .getByRole("row")
      .filter({ hasText: "SYNTH" }),
  ).toContainText("Hypothetical");
  await toggle.uncheck();
  await expect(page.getByTestId("win-rate")).toHaveText("100.00%");
  fail = true;
  await toggle.check();
  await expect(page.getByRole("alert")).toContainText(
    "Latest prices unavailable",
  );
  await expect(page.getByTestId("win-rate")).toBeHidden();
  fail = false;
  await page.getByRole("button", { name: "Retry scorecard" }).click();
  await expect(page.getByTestId("win-rate")).toHaveText("50.00%");
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});
