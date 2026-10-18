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

test("economic research keeps dated observations, gaps and range controls", async ({
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
  await expect(page.locator(".economics-selected-value")).toContainText(
    "4.125 USD per pound · Sep 2026",
  );
  await expect(
    page.getByRole("img", { name: /Example food price/ }),
  ).toBeVisible();
  await expect(page.getByLabel("From", { exact: true })).toHaveValue(
    "2026-01-01",
  );
  await expect(page.getByLabel("Through", { exact: true })).toHaveValue(
    "2026-09-01",
  );
  await expect(page.locator(".economics-line")).toHaveCount(2);
  await expect(page.locator(".economics-data-table tbody tr")).toHaveCount(0);
  await page.getByText("Data table (5 observations)", { exact: true }).click();
  await expect(page.locator(".economics-data-table tbody tr")).toHaveCount(5);
  await expect(page.locator(".economics-data-table a")).toHaveCount(0);
  await expect(
    page.getByRole("columnheader", { name: "Notes", exact: true }),
  ).toBeVisible();
  await page.getByText("Data table (5 observations)", { exact: true }).click();
  await expect(page.locator(".economics-data-table tbody tr")).toHaveCount(0);
  await page.getByText("Data table (5 observations)", { exact: true }).click();
  await expect(page.locator(".economics-data-table tbody tr")).toHaveCount(5);
  await expect(
    page.getByRole("cell", { name: "Unavailable", exact: true }),
  ).toBeVisible();
  await page.getByText("About this measure", { exact: true }).click();
  await expect(
    page.getByText("Automatic collection is off.", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("A licensed data feed is required.", { exact: false }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("link", { name: "Example Statistics", exact: true }),
  ).toBeVisible();
  await page.getByLabel("From", { exact: true }).fill("2026-08-01");
  await expect(
    page.getByText("Data table (2 observations)", { exact: true }),
  ).toBeVisible();
  await expect(page.locator(".economics-chart circle")).toHaveCount(2);
  await page.getByLabel("Through", { exact: true }).fill("2026-08-01");
  await expect(
    page.getByText("Data table (1 observations)", { exact: true }),
  ).toBeVisible();
  await expect(page.locator(".economics-chart circle")).toHaveCount(1);
  await expect(
    page.getByRole("rowheader", { name: "Aug 2026", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("rowheader", { name: "Sep 2026", exact: true }),
  ).toHaveCount(0);
  await page.getByLabel("Through", { exact: true }).fill("2026-09-01");
  await expect(
    page.getByText("Data table (2 observations)", { exact: true }),
  ).toBeVisible();
  await expect(page.locator(".economics-chart circle")).toHaveCount(2);
  await page.getByLabel("Through", { exact: true }).fill("2026-07-01");
  await expect(page.getByRole("alert")).toHaveText(
    "The end date must be on or after the start date.",
  );
  await page.getByRole("button", { name: "All dates" }).click();
  await expect(page.getByLabel("From", { exact: true })).toHaveValue(
    "2026-01-01",
  );
  await expect(page.getByLabel("Through", { exact: true })).toHaveValue(
    "2026-09-01",
  );
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
  description:
    key === "equity-gdp"
      ? "Fed publicly traded equity includes closed-end funds and ETFs; divided by nominal annualized GDP for the same quarter."
      : series.description,
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

test("grouped measure picker keeps periods and selected-source details clear", async ({
  page,
  isMobile,
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
    page.getByRole("img", { name: /Headline CPI inflation/ }),
  ).toBeVisible();
  const chartPosition = await page
    .getByRole("img", { name: /Headline CPI inflation/ })
    .boundingBox();
  expect(chartPosition!.y).toBeLessThan(550);
  const measure = page.getByLabel("Measure", { exact: true });
  const choices = page.getByRole("listbox", { name: "Measures", exact: true });
  await measure.click();
  await expect(measure).toHaveAttribute("aria-expanded", "true");
  await expect(choices.getByRole("option")).toHaveCount(macroSeries.length + 1);
  await expect(choices.getByRole("group")).toHaveCount(3);
  await expect(
    choices
      .getByRole("group", { name: "Macro indicators", exact: true })
      .getByRole("option"),
  ).toHaveCount(macroSeries.filter((item) => item.category === "macro").length);
  await expect(
    choices
      .getByRole("group", { name: "Market valuation", exact: true })
      .getByRole("option"),
  ).toHaveCount(2);
  await expect(
    choices
      .getByRole("group", { name: "Household costs", exact: true })
      .getByRole("option"),
  ).toHaveCount(1);
  await expect(
    choices.locator("strong").filter({ hasText: /^Macro indicators$/ }),
  ).toHaveCSS("font-weight", "700");
  await expect(
    choices.getByRole("option", {
      name: "Headline CPI inflation",
      exact: true,
    }),
  ).toHaveCSS("padding-left", "24px");
  await expect(
    choices.getByRole("option", { name: "Real GDP growth", exact: true }),
  ).toBeAttached();
  const dropdown = await page
    .getByRole("listbox", { name: "Measures", exact: true })
    .evaluate((element) => ({
      height: element.clientHeight,
      scrollHeight: element.scrollHeight,
    }));
  expect(dropdown.height).toBeLessThanOrEqual(280);
  expect(dropdown.scrollHeight).toBeGreaterThan(dropdown.height);
  await measure.press("ArrowDown");
  await expect(measure).toHaveAttribute(
    "aria-activedescendant",
    "economic-measure-core-pce-inflation",
  );
  await measure.press("ArrowUp");
  await expect(measure).toHaveAttribute(
    "aria-activedescendant",
    "economic-measure-headline-inflation",
  );
  for (
    let step = 0;
    step < macroSeries.filter((item) => item.category === "macro").length;
    step++
  )
    await measure.press("ArrowDown");
  await expect(measure).toHaveAttribute(
    "aria-activedescendant",
    "economic-measure-cape",
  );
  await measure.press("ArrowUp");
  await expect(measure).toHaveAttribute(
    "aria-activedescendant",
    "economic-measure-gasoline",
  );
  await measure.press("Escape");
  await measure.click();
  await measure.pressSequentially("CAP");
  await expect(measure).toHaveValue("CAP");
  await expect(choices.getByRole("option")).toHaveCount(1);
  await expect(choices.getByRole("option")).toHaveText("Shiller CAPE");
  await expect(choices.getByRole("group")).toHaveCount(1);
  await expect(
    choices.getByRole("group", { name: "Market valuation", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("img", { name: /Headline CPI inflation/ }),
  ).toBeVisible();
  await measure.press("ArrowDown");
  await measure.press("Enter");
  await expect(page.getByRole("img", { name: /Shiller CAPE/ })).toBeVisible();
  await measure.fill("No such measure");
  await expect(page.getByRole("status")).toHaveText("No matching measures.");
  await expect(page.getByRole("img", { name: /Shiller CAPE/ })).toBeVisible();
  await measure.press("Escape");
  await expect(measure).toHaveValue("Shiller CAPE");
  await measure.fill("Buffett");
  await expect(choices.getByRole("option")).toHaveCount(1);
  await expect(choices.getByRole("option")).toHaveText(
    "Buffett-style equity/GDP proxy",
  );
  const buffettOption = choices.getByRole("option", {
    name: "Buffett-style equity/GDP proxy",
    exact: true,
  });
  if (isMobile) await buffettOption.tap();
  else await buffettOption.click();
  await expect(
    page.getByRole("img", { name: /Buffett-style equity\/GDP proxy/ }),
  ).toBeVisible();
  await expect(measure).toHaveAttribute("aria-expanded", "false");
  await measure.fill("No match");
  await page.getByLabel("From", { exact: true }).click();
  await expect(measure).toHaveValue("Buffett-style equity/GDP proxy");
  await measure.fill("Headline CPI inflation");
  await measure.press("Enter");
  await expect(
    page.getByRole("img", { name: /Headline CPI inflation/ }),
  ).toBeVisible();
  await expect(page.getByLabel("From", { exact: true })).toHaveValue(
    "2026-07-01",
  );
  await expect(page.getByLabel("Through", { exact: true })).toHaveValue(
    "2026-09-01",
  );
  await page.getByLabel("From", { exact: true }).fill("2026-08-01");
  await expect(
    page.getByText("Data table (2 observations)", { exact: true }),
  ).toBeVisible();
  await expect(page.getByLabel("From", { exact: true })).toHaveValue(
    "2026-08-01",
  );
  await page.getByLabel("Measure", { exact: true }).fill("Real GDP growth");
  await measure.press("Enter");
  await expect(page.getByLabel("From", { exact: true })).toHaveValue(
    "2026-01-01",
  );
  await expect(page.getByLabel("Through", { exact: true })).toHaveValue(
    "2026-07-01",
  );
  await expect(
    page.getByRole("img", { name: /Real GDP growth.*Q1 2026 to Q3 2026/ }),
  ).toBeVisible();
  await expect(page.locator(".economics-chart circle")).toHaveCount(3);
  await expect(page.getByText("Latest readings", { exact: true })).toHaveCount(
    0,
  );
  await expect(
    page.getByText("Sources & collection schedule", { exact: true }),
  ).toHaveCount(0);
  await expect(
    page.locator("summary").filter({ hasText: /^Household costs$/ }),
  ).toHaveCount(0);
  await measure.fill("Monthly payroll change");
  await measure.press("Enter");
  await expect(page.locator(".economics-selected-value")).toContainText(
    "150 Thousands of jobs",
  );
  await measure.fill("Payroll change, 3-month average");
  await measure.press("Enter");
  await expect(page.locator(".economics-selected-value")).toContainText(
    "125 Thousands of jobs",
  );
  await measure.fill("Fed target lower bound");
  await measure.press("Enter");
  await expect(
    page.getByRole("img", { name: /Fed target lower bound/ }),
  ).toBeVisible();
  await expect(page.locator(".economics-selected-value")).toContainText(
    "4.25 Percent",
  );
  await expect(page.locator(".economics-line")).toHaveAttribute(
    "d",
    /H[\d.]+ V[\d.]+/,
  );
  await expect(page.locator(".economics-line")).not.toHaveAttribute("d", / L/);
  await measure.fill("Fed target upper bound");
  await measure.press("Enter");
  await expect(page.locator(".economics-selected-value")).toContainText(
    "4.5 Percent",
  );
  await measure.fill("Financial stress index");
  await measure.press("Enter");
  await expect(
    page.getByText("No observations collected for these dates."),
  ).toBeVisible();
  await expect(page.getByRole("status")).toHaveText(
    "Source unavailable: A permitted numerical download is not yet available.",
  );
  await expect(page.getByRole("img")).toHaveCount(0);
  await measure.fill("Buffett-style equity/GDP proxy");
  await measure.press("Enter");
  await expect(page.locator(".economics-selected-value")).toContainText(
    "Q3 2026",
  );
  await expect(
    page.getByText(
      /Fed publicly traded equity includes closed-end funds and ETFs/,
    ),
  ).toBeHidden();
  await page.getByText("About this measure", { exact: true }).click();
  await expect(
    page.getByText(
      /Fed publicly traded equity includes closed-end funds and ETFs/,
    ),
  ).toBeVisible();
  await measure.fill("Shiller CAPE");
  await measure.press("Enter");
  await expect(page.locator(".economics-selected-value")).toContainText(
    "Sep 2026 · Provisional",
  );
  await page.getByText("Data table (3 observations)", { exact: true }).click();
  await expect(
    page.getByText("Latest CPI inputs are estimated.", { exact: false }),
  ).toBeVisible();
  await expect(
    page.getByText("Latest source month is provisional.", { exact: false }),
  ).toHaveCount(0);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});

test("all dates keeps a missing latest period and imported snapshots do not claim publisher checks", async ({
  page,
}) => {
  const missingLatest = {
    ...observations[0],
    date: "2026-10-01",
    value: null,
    missing: true,
    footnotes: [{ text: "The publisher has not reported this period." }],
  };
  const definition = { ...series, latest: missingLatest, observation_count: 6 };
  await page.route("**/api/research/economics", (route) =>
    route.fulfill({
      json: {
        sources: [{ ...source, status: "imported" }],
        series: [definition],
      },
    }),
  );
  await page.route("**/api/research/economics/series/*", (route) =>
    route.fulfill({
      json: {
        series: definition,
        observations: [...observations, missingLatest],
      },
    }),
  );
  await page.goto("/#research/economics");
  await expect(page.getByLabel("From", { exact: true })).toHaveValue(
    "2026-01-01",
  );
  await expect(page.getByLabel("Through", { exact: true })).toHaveValue(
    "2026-10-01",
  );
  await expect(
    page.getByRole("img", { name: /Jan 2026 to Oct 2026/ }),
  ).toBeVisible();
  await page.getByText("Data table (6 observations)", { exact: true }).click();
  await expect(
    page.getByRole("rowheader", { name: "Oct 2026", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("The publisher has not reported this period.", {
      exact: false,
    }),
  ).toBeVisible();
  await page.getByLabel("Through", { exact: true }).fill("2026-09-01");
  await expect(
    page.getByText("Data table (5 observations)", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "All dates" }).click();
  await expect(page.getByLabel("Through", { exact: true })).toHaveValue(
    "2026-10-01",
  );
  await expect(
    page.getByRole("rowheader", { name: "Oct 2026", exact: true }),
  ).toBeVisible();
  await page.getByText("About this measure", { exact: true }).click();
  await expect(
    page.getByText(/^Imported on .*; publisher not checked\.$/),
  ).toBeVisible();
  await expect(page.getByText(/Last checked:/)).toHaveCount(0);
  await page.route("**/api/research/economics", (route) =>
    route.fulfill({
      json: {
        sources: [
          {
            ...source,
            status: "failed",
            error: "Publisher connection unavailable.",
          },
        ],
        series: [definition],
      },
    }),
  );
  await page.reload();
  await expect(
    page.getByRole("img", { name: /Example food price/ }),
  ).toBeVisible();
  await page.getByText("About this measure", { exact: true }).click();
  await expect(
    page.getByText(/Last checked: .*Last accepted data:/),
  ).toBeVisible();
  await expect(
    page.getByText("Last successful collection", { exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByText(
      "Last collection failed: Publisher connection unavailable.",
      { exact: true },
    ),
  ).toBeVisible();
});
