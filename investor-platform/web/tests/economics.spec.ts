import { expect, test } from "@playwright/test";

const source = {
  id: "example",
  name: "Example Statistics",
  url: "https://example.com/data",
  publication_frequency: "Monthly",
  publication_schedule: "Second week of the month",
  polling_frequency: "Daily",
  cadence_url: "https://example.com/calendar",
  enabled: true,
  disabled_reason: null,
  status: "complete",
  last_attempt: "2026-10-18T12:00:00Z",
  last_success: "2026-10-18T12:00:00Z",
  next_due: "2026-10-19T12:00:00Z",
  error: null,
};
const series = {
  key: "example-food",
  source_id: "example",
  name: "Example food price",
  unit: "USD per pound",
  frequency: "Monthly",
  description: "A monthly average retail price.",
  methodology_notes: "National average, not seasonally adjusted.",
  source_url: "https://example.com/data",
  latest: { date: "2026-09-01", value: "4.125", missing: false },
  observation_count: 5,
};
const observations = [
  { date: "2026-01-01", value: "3.5", missing: false },
  { date: "2026-02-01", value: "3.6", missing: false },
  { date: "2026-03-01", value: null, missing: true },
  { date: "2026-08-01", value: "4.0", missing: false },
  { date: "2026-09-01", value: "4.125", missing: false },
].map((point) => ({
  ...point,
  source_url: "https://example.com/data",
  footnotes: [],
  derived_from: null,
}));

test.beforeEach(async ({ page }) => {
  await page.route("**/api/accounts", (route) => route.fulfill({ json: [] }));
  await page.route("**/api/research/managers", (route) =>
    route.fulfill({ json: { managers: [] } }),
  );
  await page.route("**/api/research/economics", (route) =>
    route.fulfill({
      json: {
        automatic_collection_enabled: false,
        sources: [
          source,
          {
            ...source,
            id: "licensed",
            name: "Example Licensed Source",
            enabled: false,
            disabled_reason: "A licensed data feed is required.",
          },
        ],
        series: [series],
      },
    }),
  );
  await page.route("**/api/research/economics/series/*", (route) => {
    const start = new URL(route.request().url()).searchParams.get("start");
    return route.fulfill({
      json: {
        series,
        observations: start
          ? observations.filter((point) => point.date >= start)
          : observations,
      },
    });
  });
});

test("economic research shows dated observations, chart gaps, cadence and a date filter", async ({
  page,
}) => {
  await page.goto("/#research");
  await page.getByRole("link", { name: "[ Economics ]", exact: true }).click();
  await expect(page).toHaveURL(/#research\/economics$/);
  await expect(
    page.getByRole("link", { name: "[ Economics ]" }),
  ).toHaveAttribute("aria-current", "page");
  await expect(
    page.getByRole("heading", { name: "Economics", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("cell", { name: "4.125", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("cell", { name: "Sep 2026", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("img", { name: /Example food price/ }),
  ).toBeVisible();
  await expect(page.locator(".economics-line")).toHaveCount(2);
  await page.getByText("Data table (5 observations)", { exact: true }).click();
  await expect(
    page.getByRole("cell", { name: "Unavailable", exact: true }),
  ).toBeVisible();
  await page
    .getByText("Sources & collection schedule", { exact: true })
    .click();
  await expect(
    page.getByText(
      "Automatic collection is off. Initial data remains available.",
      { exact: true },
    ),
  ).toBeVisible();
  await expect(page.getByText("Next check due", { exact: true })).toHaveCount(
    0,
  );
  await expect(
    page.getByText("A licensed data feed is required.", { exact: false }),
  ).toBeVisible();
  await expect(
    page.getByText("Second week of the month", { exact: false }).first(),
  ).toBeVisible();
  await expect(page.getByText("Daily", { exact: true })).toBeVisible();
  await page.getByLabel("From", { exact: true }).fill("2026-08-01");
  await expect(
    page.getByText("Data table (2 observations)", { exact: true }),
  ).toBeVisible();
  await page.getByLabel("Through", { exact: true }).fill("2026-07-01");
  await expect(page.getByRole("alert")).toHaveText(
    "The end date must be on or after the start date.",
  );
  await page.getByRole("button", { name: "All dates" }).click();
  await expect(
    page.getByText("Data table (5 observations)", { exact: true }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "Economics", exact: true }),
  ).toBeVisible();
});

test("empty histories and a series request failure have clear recovery", async ({
  page,
}) => {
  let fail = true;
  await page.route("**/api/research/economics/series/*", (route) =>
    fail
      ? route.fulfill({ status: 503, json: {} })
      : route.fulfill({ json: { series, observations: [] } }),
  );
  await page.goto("/#research/economics");
  await expect(
    page.getByRole("button", { name: "Retry series" }),
  ).toBeVisible();
  fail = false;
  await page.getByRole("button", { name: "Retry series" }).click();
  await expect(
    page.getByText("No observations collected for these dates."),
  ).toBeVisible();
  await expect(page.getByRole("img")).toHaveCount(0);
});

test("catalog failure can retry into an empty catalog", async ({ page }) => {
  let fail = true;
  await page.route("**/api/research/economics", (route) =>
    fail
      ? route.fulfill({ status: 503, json: {} })
      : route.fulfill({ json: { sources: [], series: [] } }),
  );
  await page.goto("/#research/economics");
  await expect(page.getByRole("alert")).toBeVisible();
  fail = false;
  await page.getByRole("button", { name: "Retry economics" }).click();
  await expect(
    page.getByText("No economic series have been added."),
  ).toBeVisible();
});
