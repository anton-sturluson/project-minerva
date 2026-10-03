import { expect, test } from "@playwright/test";

test("shows market hit rate, exclusions, outage recovery, and invalidates after a save", async ({
  page,
}) => {
  let state: "outage" | "ready" | "empty" = "outage";
  await page.route("**/hit-rate", (route) => {
    if (state === "outage")
      return route.fulfill({
        status: 503,
        json: {
          detail:
            "Hit rate data is unavailable. Retry; saved records are unchanged.",
        },
      });
    const empty = state === "empty";
    return route.fulfill({
      json: {
        benchmarks: {
          SPY: {
            hit_rate: empty ? null : "0.5",
            hits: empty ? 0 : 1,
            evaluated: empty ? 0 : 2,
            ties: 0,
          },
          QQQ: {
            hit_rate: empty ? null : "0",
            hits: 0,
            evaluated: empty ? 0 : 2,
            ties: empty ? 0 : 1,
          },
        },
        excluded: 1,
        open: 1,
        source: "Synthetic market fixture",
        fetched_at: "2026-02-01T12:00:00Z",
        episodes: [
          {
            ticker: "DEMO",
            exchange: "NASDAQ",
            opened_on: "2026-01-02",
            closed_on: "2026-01-05",
            excluded: "Opening position: original purchase dates are unknown",
          },
        ],
      },
    });
  });
  await page.goto("/");
  const calculate = page.getByRole("button", {
    name: "Calculate hit rate",
    exact: true,
  });
  await calculate.click();
  await expect(page.getByRole("alert")).toContainText(
    "Hit rate data is unavailable",
  );
  await expect(page.getByTestId("payoff-ratio")).toBeVisible();
  state = "ready";
  await calculate.click();
  await expect(page.getByTestId("hit-rate-SPY")).toHaveText("50.00%");
  await expect(page.getByTestId("hit-rate-QQQ")).toHaveText("0.00%");
  await expect(page.getByRole("alert")).toBeHidden();
  await page
    .getByText("Hit rate method & decision results", { exact: true })
    .click();
  await expect(page.getByLabel("Hit rate decisions")).toContainText(
    "original purchase dates are unknown",
  );
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.getByLabel("Cash amount").fill("1");
  await page.getByLabel("Cash note").fill("Synthetic hit-rate invalidation");
  await page.getByRole("button", { name: "Save cash entry" }).click();
  await expect(
    page.getByText("Cash entry saved.", { exact: true }),
  ).toBeVisible();
  await expect(page.getByTestId("hit-rate-SPY")).toHaveText("—");
  state = "empty";
  await calculate.click();
  await expect(
    page.getByText(
      "No eligible closed decisions. Hit rate is unavailable, not zero.",
      { exact: true },
    ),
  ).toBeVisible();
  await expect(page.getByTestId("hit-rate-QQQ")).toHaveText("—");
});
