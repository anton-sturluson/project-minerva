import { expect, test } from "@playwright/test";
import { performance } from "./fixtures";

const account = {
  id: "00000000-0000-4000-8000-000000000094",
  name: "Synthetic refresh portfolio",
  base_currency: "USD",
  created_at: "2026-01-02T12:00:00Z",
};
const ledger = {
  balance: "1000",
  currency: "USD",
  holdings: [],
  entries: [
    {
      id: 1,
      kind: "opening_cash",
      effective_date: "2026-01-02",
      amount: "1000",
      currency: "USD",
      note: "Synthetic",
      security: null,
    },
  ],
};

test.beforeEach(async ({ page }) => {
  await page.clock.install({ time: new Date("2026-11-04T23:00:00Z") });
  await page.route("**/api/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/accounts") return route.fulfill({ json: [account] });
    if (path.endsWith("/ledger")) return route.fulfill({ json: ledger });
    if (path.endsWith("/valuation"))
      return route.fulfill({
        json: {
          end: "2026-11-04",
          value: "1000",
          cash: "1000",
          complete: true,
          provisional: false,
          holdings: [],
        },
      });
    if (path.endsWith("/performance")) {
      const request = route.request().postDataJSON();
      return route.fulfill({
        json: { ...performance, start: request.start, end: request.end },
      });
    }
    if (path.endsWith("/statistics"))
      return route.fulfill({
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
      });
    if (path === "/api/research/managers")
      return route.fulfill({ json: { managers: [] } });
    if (path === "/api/market-data/status")
      return route.fulfill({
        json: {
          enabled: true,
          worker_alive: true,
          last_attempt_at: "2026-11-04T22:00:00Z",
          last_success_at: "2026-11-02T22:00:00Z",
          next_due_at: "2026-11-05T22:00:00Z",
          release: "synthetic-release",
          report: {
            status: "partial",
            failures: [
              {
                symbol: "SYN",
                scope: "history",
                reason: "currency_unavailable",
              },
            ],
          },
        },
      });
    return route.fulfill({
      status: 404,
      json: { detail: "Synthetic route unavailable" },
    });
  });
});

test("one price refresh recovers comparison and shows worker health", async ({
  page,
}) => {
  let unavailable = true;
  await page.route("**/performance", (route) =>
    unavailable
      ? route.fulfill({
          status: 503,
          json: { detail: "Synthetic price outage" },
        })
      : route.fulfill({ json: performance }),
  );
  await page.goto("/");
  await expect(
    page.getByText("Synthetic price outage", { exact: true }),
  ).toBeVisible();
  unavailable = false;
  await page.getByRole("button", { name: "Reload data", exact: true }).click();
  await expect(
    page.getByRole("img", { name: /Cumulative portfolio/ }),
  ).toBeVisible();
  await expect(
    page.getByText("Synthetic price outage", { exact: true }),
  ).toHaveCount(0);
  const status = page.getByRole("region", { name: "Daily price updates" });
  await expect(status).toContainText(
    "Daily price updates across all portfolios: running",
  );
  await expect(status).toContainText("Latest attempt: partial");
  await status.getByText("Price update details", { exact: true }).click();
  await expect(status).toContainText("SYN: currency unavailable (history)");
  await expect(status).toContainText("synthetic-release");
  await page.screenshot({
    path: test.info().outputPath("price-update-status.png"),
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});

test("returning on a new day advances latest periods but preserves custom dates and cash drafts", async ({
  page,
}) => {
  await page.goto("/");
  await expect(
    page.getByRole("button", { name: "Compare performance", exact: true }),
  ).toBeEnabled();
  await page.getByRole("link", { name: "[ Activity ]", exact: true }).click();
  await page.getByText("Record cash", { exact: true }).click();
  await page.getByLabel("Cash amount", { exact: true }).fill("123");
  await page.clock.setSystemTime(new Date("2026-11-05T23:00:00Z"));
  await page.getByRole("link", { name: "[ Portfolio ]", exact: true }).click();
  await expect(page.getByLabel("Performance end")).toHaveValue("2026-11-05");
  await expect(
    page.getByRole("button", { name: "Compare performance", exact: true }),
  ).toBeEnabled();
  await page.getByLabel("Performance end").fill("2026-10-30");
  await page
    .getByRole("button", { name: "Compare performance", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Compare performance", exact: true }),
  ).toBeEnabled();
  await page.clock.setSystemTime(new Date("2026-11-06T23:00:00Z"));
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  await expect(
    page.getByRole("button", { name: "Compare performance", exact: true }),
  ).toBeEnabled();
  await expect(page.getByLabel("Performance end")).toHaveValue("2026-10-30");
  await page.getByRole("link", { name: "[ Activity ]", exact: true }).click();
  await expect(page.getByLabel("Cash amount", { exact: true })).toHaveValue(
    "123",
  );
});

test("caller cancellation stops API reads", async ({ page }) => {
  await page.goto("/#research");
  const result = await page.evaluate(async () => {
    const modulePath = "/src/api.ts";
    const { api } = await import(modulePath);
    const controller = new AbortController();
    controller.abort();
    try {
      await api("/accounts", { signal: controller.signal });
      return "resolved";
    } catch (error) {
      return (error as Error).name;
    }
  });
  expect(result).toBe("AbortError");
});

test("status failure leaves portfolio usable and recovers to disabled", async ({
  page,
}) => {
  let unavailable = true;
  await page.route("**/market-data/status", (route) =>
    unavailable
      ? route.fulfill({
          status: 503,
          json: { detail: "Synthetic status outage" },
        })
      : route.fulfill({
          json: {
            enabled: false,
            worker_alive: false,
            last_attempt_at: null,
            last_success_at: null,
            next_due_at: null,
            report: null,
            release: "synthetic-release",
          },
        }),
  );
  await page.goto("/");
  await expect(
    page.getByRole("img", { name: /Cumulative portfolio/ }),
  ).toBeVisible();
  await expect(page.getByText(/Price update status unavailable/)).toBeVisible();
  unavailable = false;
  await page.getByRole("button", { name: "Retry status" }).click();
  await expect(
    page.getByRole("region", { name: "Daily price updates" }),
  ).toContainText("Daily price updates across all portfolios: disabled");
  await expect(
    page.getByRole("img", { name: /Cumulative portfolio/ }),
  ).toBeVisible();
});

test("same-day return and focus pick up accepted prices after a collector retry", async ({
  page,
}) => {
  let value = "1200";
  await page.route("**/performance", (route) =>
    route.fulfill({ json: { ...performance, value } }),
  );
  await page.goto("/");
  await expect(page.getByText("1,200.00", { exact: true })).toBeVisible();
  await page.getByLabel("Performance end").fill("2026-10-30");
  await page
    .getByRole("button", { name: "Compare performance", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Compare performance", exact: true }),
  ).toBeEnabled();
  await page.getByRole("link", { name: "[ Research ]", exact: true }).click();
  value = "1300";
  await page.clock.setSystemTime(new Date("2026-11-04T23:30:00Z"));
  await page.getByRole("link", { name: "[ Portfolio ]", exact: true }).click();
  await expect(page.getByText("1,300.00", { exact: true })).toBeVisible();
  value = "1400";
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  await expect(page.getByText("1,400.00", { exact: true })).toBeVisible();
  await expect(page.getByLabel("Performance end")).toHaveValue("2026-10-30");
});
