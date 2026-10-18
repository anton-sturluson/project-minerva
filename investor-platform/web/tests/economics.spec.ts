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
  await page.getByText("Household costs", { exact: true }).click();
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

const macroSeries = [
  [
    "headline-inflation",
    "Headline CPI inflation",
    "Percent, 12-month change",
    "Monthly",
    "2.4",
  ],
  [
    "core-pce-inflation",
    "Core PCE inflation",
    "Percent, 12-month change",
    "Monthly",
    "2.8",
  ],
  [
    "real-gdp-growth",
    "Real GDP growth",
    "Percent, q/q annualized",
    "Quarterly",
    "3.1",
  ],
  ["unemployment", "Unemployment rate", "Percent", "Monthly", "4.1"],
  [
    "payroll-growth",
    "Monthly payroll change",
    "Thousands of jobs",
    "Monthly",
    "150",
  ],
  [
    "payroll-growth-3m",
    "Payroll change, 3-month average",
    "Thousands of jobs",
    "Monthly",
    "125",
  ],
  [
    "real-consumption-growth",
    "Real consumer spending growth",
    "Percent, 12-month change",
    "Monthly",
    "2.2",
  ],
  ["fed-target-lower", "Fed target lower bound", "Percent", "Daily", "4.25"],
  ["fed-target-upper", "Fed target upper bound", "Percent", "Daily", "4.5"],
  ["treasury-10y", "10-year Treasury yield", "Percent", "Daily", "4.15"],
  ["mortgage-30y", "30-year fixed mortgage rate", "Percent", "Weekly", "6.2"],
  ["financial-stress", "Financial stress index", "Index", "Weekly", "-0.35"],
  ["gasoline", "Regular gasoline", "USD per gallon", "Weekly", "3.125"],
  ["cape", "Shiller CAPE", "Ratio", "Monthly", "38.5"],
  [
    "equity-gdp",
    "Buffett-style equity/GDP proxy",
    "Percent of GDP",
    "Quarterly",
    "195.2",
  ],
].map(([key, name, unit, frequency, value]) => ({
  ...series,
  key,
  name,
  unit,
  frequency,
  category: ["cape", "equity-gdp"].includes(key) ? "valuation" : "macro",
  source_id: key === "financial-stress" ? "stress" : "example",
  latest:
    key === "financial-stress"
      ? null
      : {
          date: frequency === "Quarterly" ? "2026-07-01" : "2026-09-01",
          value,
          missing: false,
          provisional: key === "cape",
        },
}));

test("macro overview keeps measures, native periods and provisional valuations clear", async ({
  page,
}) => {
  await page.route("**/api/research/economics", (route) =>
    route.fulfill({
      json: {
        sources: [
          source,
          {
            ...source,
            id: "stress",
            enabled: false,
            disabled_reason:
              "A permitted numerical download is not yet available.",
          },
        ],
        series: [...macroSeries, { ...series, category: "household" }],
      },
    }),
  );
  await page.route("**/api/research/economics/series/*", (route) => {
    const key = new URL(route.request().url()).pathname.split("/").at(-1);
    const item = macroSeries.find((item) => item.key === key) ?? series;
    const quarterly = item.frequency === "Quarterly";
    const dated = (
      quarterly
        ? ["2026-01-01", "2026-04-01", "2026-07-01"]
        : ["2026-07-01", "2026-08-01", "2026-09-01"]
    ).map((date, index) => ({
      ...observations[0],
      date,
      value: index === 0 ? "-1.2" : "2.3",
      provisional: key === "cape" && index === 2,
      footnotes:
        key === "cape" && index === 2
          ? [{ text: "Latest CPI inputs are estimated." }]
          : [],
    }));
    return route.fulfill({
      json: {
        series: item,
        observations: key === "financial-stress" ? [] : dated,
      },
    });
  });
  await page.goto("/#research/economics");
  await expect(
    page.getByRole("heading", { name: "U.S. macro overview" }),
  ).toBeVisible();
  await expect(
    page.locator(".economics-overview").first().locator(".economics-panel"),
  ).toHaveCount(8);
  await expect(
    page
      .getByRole("region", { name: "Jobs", exact: true })
      .getByText("150", { exact: true }),
  ).toBeVisible();
  await expect(
    page
      .getByRole("region", { name: "Jobs", exact: true })
      .getByText("125", { exact: true }),
  ).toBeVisible();
  await expect(
    page
      .getByRole("region", { name: "Interest rates", exact: true })
      .getByText("4.25", { exact: true }),
  ).toBeVisible();
  await expect(
    page
      .getByRole("region", { name: "Interest rates", exact: true })
      .getByText("4.5", { exact: true }),
  ).toBeVisible();
  await expect(
    page
      .getByRole("region", { name: "Economic growth", exact: true })
      .getByText("Q3 2026", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("region", {
      name: "Buffett-style equity/GDP proxy",
      exact: true,
    }),
  ).toBeVisible();
  await expect(
    page.getByText("Sep 2026 · Provisional", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText(
      /Fed publicly traded equity includes closed-end funds and ETFs/,
    ),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Example food price", exact: true }),
  ).toBeHidden();
  await page
    .getByRole("button", { name: "Real GDP growth", exact: true })
    .click();
  await expect(
    page.getByRole("img", { name: /Real GDP growth.*Q1 2026 to Q3 2026/ }),
  ).toBeVisible();
  await expect(page.locator(".economics-chart circle")).toHaveCount(3);
  await page
    .getByRole("button", { name: "Fed target lower bound", exact: true })
    .click();
  await expect(
    page.getByRole("img", { name: /Fed target lower bound/ }),
  ).toBeVisible();
  await expect(page.locator(".economics-line")).toHaveAttribute(
    "d",
    /H[\d.]+ V[\d.]+/,
  );
  await expect(page.locator(".economics-line")).not.toHaveAttribute("d", / L/);
  await expect(page.getByText(/steps preserve each target/)).toBeVisible();
  await expect(
    page
      .getByRole("region", { name: "Financial stress", exact: true })
      .getByText("Unavailable", { exact: true }),
  ).toBeVisible();
  await expect(
    page
      .getByRole("region", { name: "Financial stress", exact: true })
      .getByText(/A permitted numerical download/),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Financial stress index", exact: true })
    .click();
  await expect(
    page.getByText("No observations collected for these dates."),
  ).toBeVisible();
  await expect(page.getByRole("img")).toHaveCount(0);
  await page.getByRole("button", { name: "Shiller CAPE", exact: true }).click();
  await expect(
    page.getByText(/Provisional observations are marked/),
  ).toBeVisible();
  await page.getByText("Data table (3 observations)", { exact: true }).click();
  await expect(
    page.getByText("Latest CPI inputs are estimated.", { exact: false }),
  ).toBeVisible();
  await page.getByText("Household costs", { exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Example food price", exact: true }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});
