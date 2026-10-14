import { expect, test } from "@playwright/test";
import type { FinancialReport } from "../src/financialApi";

function report(year = 2025): FinancialReport {
  return {
    synthetic: true,
    calendar_year: year,
    holdings_date: `${year}-12-31`,
    api_status: "partial",
    market_value_snapshot: {
      holdings: [
        { issuer_key: "example:issuer", ticker: "EXM" },
        { issuer_key: "example:excluded", ticker: "OTH" },
      ],
    },
    companies: [
      {
        issuer_key: "example:issuer",
        equity_weight: "0.75",
        financial_status: "eligible",
        profile: {
          review_status: "reviewed",
          issuer: { name: "Example Company" },
          facts: {
            basic_eps: {
              status: "reported",
              value: "2.34",
              source_id: "filing",
            },
          },
          calculations: {
            allocated_fcf_after_disclosed_capex_per_basic_share: {
              status: "calculated",
              value: year === 2023 ? "-0.00321" : "0.123456",
            },
          },
          sources: [
            {
              source_id: "filing",
              url: "https://example.org/annual-report",
              published_on: `${year + 1}-02-01`,
            },
          ],
        },
      },
      {
        issuer_key: "example:excluded",
        equity_weight: "0.25",
        financial_status: "eligible",
        profile: {
          review_status: "reviewed",
          issuer: { name: "Other Example Company" },
          facts: { basic_eps: { status: "reported", value: "6.78" } },
          calculations: {
            allocated_fcf_after_disclosed_capex_per_basic_share: {
              status: "calculated",
              value: "0.9",
            },
          },
          sources: [],
        },
      },
    ],
    weighted_ratios: {
      gross_margin: {
        label: "Gross margin",
        value: "0.40",
        coverage: "0.75",
        exclusions: [
          {
            issuer_key: "example:excluded",
            reason: "Gross margin is not applicable for an insurer.",
          },
        ],
      },
      operating_margin: {
        label: "Operating margin",
        value: year === 2023 ? "0.11" : "-0.125",
        coverage: "0.75",
        exclusions: [
          {
            issuer_key: "example:excluded",
            reason: "Annual operating figure not collected.",
          },
        ],
      },
      net_margin: {
        label: "Consolidated net margin",
        value: "0.10",
        coverage: "1",
        exclusions: [],
      },
      net_margin_common: {
        label: "Common-shareholder net margin",
        value: "0.12",
        coverage: "1",
        exclusions: [],
      },
      cfo_margin: {
        label: "Consolidated CFO margin",
        value: "0.15",
        coverage: "1",
        exclusions: [],
      },
      fcf_margin_after_disclosed_capex: {
        label: "FCF margin after disclosed cash capital spending",
        value: "0.13",
        coverage: "1",
        exclusions: [],
      },
      fcf_margin_after_ppe: {
        label: "FCF margin after cash PP&E capex",
        value: null,
        coverage: "0",
        exclusions: [
          {
            issuer_key: "example:issuer",
            reason: "Missing/applicability inputs: cash_capex_ppe",
          },
        ],
      },
    },
    weighted_company_per_share: {
      weighted_company_eps: {
        label: "Weighted company EPS",
        value: "3.45",
        coverage: "1",
        exclusions: [],
      },
      weighted_company_fcf_per_share: {
        label: "Weighted company FCF/share",
        value: year === 2023 ? "0.2225925" : "0.317592",
        coverage: "1",
        exclusions: [],
      },
    },
  };
}

test.beforeEach(async ({ page }) => {
  await page.route("**/api/accounts", (route) => route.fulfill({ json: [] }));
});

test("main weighted company values lead and company details stay collapsed", async ({
  page,
}) => {
  await page.route("**/api/financials?year=*", (route) =>
    route.fulfill({
      json: report(
        Number(new URL(route.request().url()).searchParams.get("year")),
      ),
    }),
  );
  await page.goto("/#post-mortem");
  const summary = page.getByRole("region", {
    name: "Portfolio-weighted metrics",
  });
  await expect(
    summary.getByRole("row", { name: /^Weighted company EPS/ }),
  ).toContainText("$3.45");
  await expect(
    summary.getByRole("row", { name: /^Weighted company FCF\/share/ }),
  ).toContainText("$0.3176");
  await expect(page.locator(".financial-per-share-table")).toBeHidden();
  await page.getByText("Company details", { exact: true }).click();
  const table = page.getByRole("region", { name: "Company per-share figures" });
  await expect(table.getByRole("row", { name: /^EXM / })).toContainText(
    "$2.34",
  );
  await expect(table.getByText("$0.1235", { exact: true })).toBeVisible();
  await page.getByLabel("Financial year").selectOption("2023");
  await page.getByText("Company details", { exact: true }).click();
  await expect(table.getByText("-$0.0032", { exact: true })).toBeVisible();
  await expect(table.getByText("-$0.00", { exact: true })).toHaveCount(0);
  expect(
    await summary.evaluate(
      (element) => element.scrollWidth <= element.clientWidth,
    ),
  ).toBe(true);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});

test("unreviewed and unavailable company values stay unavailable", async ({
  page,
}) => {
  await page.route("**/api/financials?year=*", (route) => {
    const year = Number(
      new URL(route.request().url()).searchParams.get("year"),
    );
    const data = report(year);
    const profile = data.companies[0].profile!;
    if (year === 2025) profile.review_status = "candidate";
    else {
      profile.facts!.basic_eps.status = "unavailable";
      profile.calculations!.allocated_fcf_after_disclosed_capex_per_basic_share.status =
        "unavailable";
    }
    return route.fulfill({ json: data });
  });
  await page.goto("/#post-mortem");
  await page.getByText("Company details", { exact: true }).click();
  const row = page
    .getByRole("region", { name: "Company per-share figures" })
    .getByRole("row", { name: /^EXM / });
  await expect(row.getByText("Unavailable", { exact: true })).toHaveCount(2);
  await expect(row.getByText("$2.34", { exact: true })).toHaveCount(0);
  await page.getByLabel("Financial year").selectOption("2024");
  await page.getByText("Company details", { exact: true }).click();
  await expect(row.getByText("Unavailable", { exact: true })).toHaveCount(2);
  await expect(row.getByText("$0.1235", { exact: true })).toHaveCount(0);
});

test("summary omits extra columns and explains exclusions from response weights", async ({
  page,
}) => {
  await page.route("**/api/accounts", (route) =>
    route.fulfill({
      status: 503,
      json: { detail: "Portfolio records temporarily unavailable" },
    }),
  );
  await page.route("**/api/financials?year=*", (route) =>
    route.fulfill({ json: report() }),
  );
  await page.goto("/#post-mortem");
  await expect(
    page.getByRole("heading", { name: /Post-mortem/, level: 1 }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Annual financials", level: 2 }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: "[ Financials ]", exact: true }),
  ).toHaveCount(0);
  const financials = page.locator(".annual-financials");
  await expect(
    financials.getByText("Illustrative weights", { exact: true }),
  ).toBeVisible();
  await expect(financials.getByText("-12.50%", { exact: true })).toBeVisible();
  await expect(
    financials.getByRole("row", { name: /^Gross margin/ }),
  ).toContainText("Gross margin*");
  await expect(
    financials.getByText("* Gross margin excludes OTH (25% weight; insurer).", {
      exact: true,
    }),
  ).toBeVisible();
  await expect(
    financials.getByText(
      "* Operating margin excludes OTH (25% weight; data unavailable).",
      { exact: true },
    ),
  ).toBeVisible();
  await expect(
    financials.getByRole("rowheader", { name: /^Weighted company EPS/ }),
  ).toHaveAttribute("aria-describedby", "weighted-share-basis");
  await expect(
    financials.getByText(
      "* Per-share figures are market-value-weighted company averages.",
      { exact: true },
    ),
  ).toBeVisible();
  await expect(
    financials.getByRole("columnheader", {
      name: /^(Coverage|Missing data|Sources)$/,
    }),
  ).toHaveCount(0);
  await expect(financials.getByRole("link")).toHaveCount(0);
  await expect(
    financials.getByText("Consolidated net margin", { exact: true }),
  ).toHaveCount(0);
  await expect(
    financials.getByText("FCF margin after cash PP&E capex", { exact: true }),
  ).toHaveCount(0);
  await expect(page.locator(".financial-weights")).toHaveCount(0);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});

test("legacy financials URL opens canonical Post-mortem", async ({ page }) => {
  await page.route("**/api/financials?year=*", (route) =>
    route.fulfill({ json: report() }),
  );
  await page.goto("/#financials");
  await expect(page).toHaveURL(/#post-mortem$/);
  await expect(
    page.getByRole("heading", { name: "Annual financials", level: 2 }),
  ).toBeVisible();
});

test("loading, transport failure and retry recover without setup details", async ({
  page,
}) => {
  let fail = true;
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route("**/api/financials?year=*", async (route) => {
    if (fail) {
      await gate;
      await route.fulfill({
        status: 503,
        json: { detail: "Private database configuration details" },
      });
    } else await route.fulfill({ json: report() });
  });
  await page.goto("/#post-mortem");
  const financials = page.locator(".annual-financials");
  await expect(financials.getByRole("status")).toHaveText(
    "Loading FY2025 financials…",
  );
  release();
  await expect(financials.getByRole("alert")).toContainText(
    "Could not load annual figures.",
  );
  await expect(
    page.getByText("Private database configuration details"),
  ).toHaveCount(0);
  fail = false;
  await financials.getByRole("button", { name: "Retry financials" }).click();
  await expect(
    financials.getByRole("region", { name: "Portfolio-weighted metrics" }),
  ).toBeVisible();
});

test("empty annual data offers retry", async ({ page }) => {
  const empty = report();
  empty.api_status = "unavailable";
  empty.companies = [];
  await page.route("**/api/financials?year=*", (route) =>
    route.fulfill({ json: empty }),
  );
  await page.goto("/#post-mortem");
  const financials = page.locator(".annual-financials");
  await expect(financials.getByRole("status")).toContainText(
    "Annual figures aren't available yet.",
  );
  await expect(
    financials.getByRole("button", { name: "Retry financials" }),
  ).toBeVisible();
  await expect(
    financials.getByRole("region", { name: "Portfolio-weighted metrics" }),
  ).toHaveCount(0);
});

test("changing financial year ignores an older late response", async ({
  page,
}) => {
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  let oldFinished!: () => void;
  const finished = new Promise<void>((resolve) => {
    oldFinished = resolve;
  });
  let oldRequested!: () => void;
  const requested = new Promise<void>((resolve) => {
    oldRequested = resolve;
  });
  await page.route("**/api/financials?year=*", async (route) => {
    const year = Number(
      new URL(route.request().url()).searchParams.get("year"),
    );
    if (year === 2024) {
      oldRequested();
      await gate;
    }
    const data = report(year);
    data.weighted_ratios.operating_margin.value =
      year === 2023 ? "0.23" : "0.24";
    await route.fulfill({ json: data });
    if (year === 2024) oldFinished();
  });
  await page.goto("/#post-mortem");
  await page.getByLabel("Financial year").selectOption("2024");
  await requested;
  await page.getByLabel("Financial year").selectOption("2023");
  await expect(
    page.locator(".annual-financials").getByText("23.00%", { exact: true }),
  ).toBeVisible();
  release();
  await finished;
  await expect(
    page.locator(".annual-financials").getByText("23.00%", { exact: true }),
  ).toBeVisible();
  await expect(
    page.locator(".annual-financials").getByText("24.00%", { exact: true }),
  ).toHaveCount(0);
});

test("annual aggregates remain visible when selected account ledger fails", async ({
  page,
}) => {
  await page.route("**/api/accounts", (route) =>
    route.fulfill({
      json: [
        {
          id: "00000000-0000-4000-8000-000000000099",
          name: "Synthetic browser test portfolio",
          base_currency: "USD",
          created_at: "2025-01-01T00:00:00Z",
        },
      ],
    }),
  );
  await page.route("**/api/accounts/*/ledger", (route) =>
    route.fulfill({
      status: 503,
      json: { detail: "Recorded ledger temporarily unavailable" },
    }),
  );
  await page.route("**/api/financials?year=*", (route) =>
    route.fulfill({ json: report() }),
  );
  await page.goto("/#post-mortem");
  await expect(
    page.getByRole("button", { name: "Reload records" }),
  ).toBeVisible();
  await expect(
    page
      .locator(".annual-financials")
      .getByRole("region", { name: "Portfolio-weighted metrics" }),
  ).toBeVisible();
});
