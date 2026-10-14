import { expect, test } from "@playwright/test";

const manager = {
  slug: "example-manager",
  name: "Example Technology Partners",
  investor_names: ["Example Investor"],
  cik: "0000000000",
  website_url: "https://example.com/",
  letters_url: "https://example.com/letters",
  focus: "Technology and software",
  history_start_year: 2010,
  history_source_url: "https://example.com/history",
  source_urls: ["https://example.com/"],
  coverage: {
    quarters: 2,
    first_quarter: "2026-03-31",
    last_quarter: "2026-06-30",
    continuous_decade: false,
  },
};
const comparison = {
  quarter: "2026-06-30",
  previous_quarter: "2026-03-31",
  status: "available",
  reason: null,
  source_urls: ["https://example.com/filing"],
  changes: [
    {
      cusip: "123456789",
      issuer: "Example Software",
      security_class: "COM",
      put_call: "",
      share_type: "SH",
      kind: "increased",
      previous_quantity: "100",
      current_quantity: "125",
      quantity_change: "25",
      value_usd: "10000",
    },
  ],
};

test("research sources, quarter changes, coverage filter and missing comparison", async ({
  page,
}) => {
  await page.route("**/api/research/managers", (route) =>
    route.fulfill({ json: { managers: [manager] } }),
  );
  await page.route("**/api/research/managers/example-manager", (route) =>
    route.fulfill({
      json: {
        ...manager,
        filings: [
          {
            quarter: "2026-06-30",
            filed_date: "2026-08-14",
            source_url: "https://example.com/filing",
          },
          {
            quarter: "2026-03-31",
            filed_date: "2026-05-14",
            source_url: "https://example.com/previous",
          },
        ],
      },
    }),
  );
  await page.route(
    "**/api/research/managers/example-manager/changes?*",
    (route) =>
      route.fulfill({
        json: route.request().url().includes("2026-03-31")
          ? {
              ...comparison,
              status: "unavailable",
              reason: "Previous quarter is missing",
              changes: [],
            }
          : comparison,
      }),
  );
  await page.goto("/#research");
  await expect(
    page.getByRole("heading", { name: "Research", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Letters & commentary" }),
  ).toHaveAttribute("href", "https://example.com/letters");
  await page.getByLabel("Verified 10-year coverage only").check();
  await expect(
    page.getByText("No managers match these filters."),
  ).toBeVisible();
  await page.getByLabel("Verified 10-year coverage only").uncheck();
  await page.getByLabel("Find a manager").fill("software");
  await page.getByRole("button", { name: manager.name }).click();
  await expect(
    page.getByRole("cell", { name: "Increased", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("cell", { name: "125", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Filing source 1" }),
  ).toHaveAttribute("href", "https://example.com/filing");
  await page.getByLabel("Report quarter").selectOption("2026-03-31");
  await expect(
    page.getByText("Comparison unavailable: Previous quarter is missing"),
  ).toBeVisible();
  await expect(
    page.getByRole("region", { name: "Quarterly position changes" }),
  ).toHaveCount(0);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});

test("research service failure can recover and empty registry is clear", async ({
  page,
}) => {
  let failure = true;
  await page.route("**/api/research/managers", (route) =>
    failure
      ? route.fulfill({
          status: 503,
          json: { detail: "Research database unavailable" },
        })
      : route.fulfill({ json: { managers: [] } }),
  );
  await page.goto("/#research");
  await expect(page.getByRole("alert")).toContainText(
    "Research database unavailable",
  );
  failure = false;
  await page.getByRole("button", { name: "Try again" }).click();
  await expect(
    page.getByText(
      "No managers loaded yet. Load the research catalog to start.",
    ),
  ).toBeVisible();
});
