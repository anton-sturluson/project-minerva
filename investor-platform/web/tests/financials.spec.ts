import { expect, test } from "@playwright/test";
import type { FinancialReport } from "../src/financialApi";

function report(year = 2025): FinancialReport {
  const source = {
    source_id: "filing",
    url: "https://example.org/annual-report",
    published_on: `${year + 1}-02-01`,
  };
  const contribution = {
    issuer_key: "example:issuer",
    calculation: { inputs: [{ source_id: "filing" }] },
  };
  return {
    synthetic: true,
    calendar_year: year,
    holdings_date: `${year}-12-31`,
    api_status: "partial",
    market_value_snapshot: {
      holdings: [{ issuer_key: "example:issuer", ticker: "EXM" }],
    },
    companies: [
      {
        issuer_key: "example:issuer",
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
              inputs: [
                { source_id: "filing" },
                { source_id: "capital-filing" },
              ],
            },
          },
          sources: [
            source,
            {
              source_id: "capital-filing",
              url: "https://example.org/capital-report",
              published_on: `${year + 1}-03-01`,
            },
            {
              source_id: "unrelated-filing",
              url: "https://example.org/unrelated-report",
              published_on: `${year + 1}-04-01`,
            },
          ],
        },
      },
    ],
    weighted_ratios: {
      gross_margin: {
        label: "Gross margin",
        value: "0.40",
        coverage: "0.75",
        exclusions: [
          { reason: "Gross margin is not applicable for an insurer." },
        ],
        contributions: [contribution],
      },
      operating_margin: {
        label: "Operating margin",
        value: year === 2023 ? "0.11" : "-0.125",
        coverage: "0.75",
        exclusions: [{ reason: "Annual operating figure not collected." }],
        contributions: [contribution],
      },
      net_margin: {
        label: "Consolidated net margin",
        value: "0.10",
        coverage: "0.40",
        exclusions: [],
      },
      net_margin_common: {
        label: "Common-shareholder net margin",
        value: "0.12",
        coverage: "1",
        exclusions: [],
        contributions: [contribution],
      },
      cfo_margin: {
        label: "Consolidated CFO margin",
        value: "0.15",
        coverage: "1",
        exclusions: [],
        contributions: [contribution],
      },
      fcf_margin_after_disclosed_capex: {
        label: "FCF margin after disclosed cash capital spending",
        value: "0.13",
        coverage: "1",
        exclusions: [],
        contributions: [
          {
            ...contribution,
            calculation: {
              ...contribution.calculation,
              review_note:
                "Mixed acquisition and capital-spending rows are excluded, not assumed zero.",
            },
          },
        ],
      },
      fcf_margin_after_ppe: {
        label: "FCF margin after cash PP&E capex",
        value: null,
        coverage: "0",
        exclusions: [
          { reason: "Missing/applicability inputs: cash_capex_ppe" },
        ],
      },
    },
  };
}

test.beforeEach(async ({ page }) => {
  await page.route("**/api/accounts", (route) => route.fulfill({ json: [] }));
});

test("company per-share dollars preserve small losses and only cite their inputs", async ({
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
  const table = page.getByRole("region", { name: "Company per-share figures" });
  await expect(table.getByRole("row", { name: /^EXM / })).toContainText(
    "$2.34",
  );
  await expect(table.getByText("$0.1235", { exact: true })).toBeVisible();
  await table.getByText("Source filings", { exact: true }).click();
  await expect(table.getByRole("link")).toHaveCount(2);
  await expect(
    table.locator('a[href="https://example.org/unrelated-report"]'),
  ).toHaveCount(0);
  await page.getByLabel("Financial year").selectOption("2023");
  await expect(table.getByText("-$0.0032", { exact: true })).toBeVisible();
  await expect(table.getByText("-$0.00", { exact: true })).toHaveCount(0);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});

test("unreviewed and unavailable per-share values stay unavailable", async ({
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
  const table = page.getByRole("region", { name: "Company per-share figures" });
  await expect(table.getByText("Unavailable", { exact: true })).toHaveCount(2);
  await expect(table.getByText("$2.34", { exact: true })).toHaveCount(0);
  await page.getByLabel("Financial year").selectOption("2024");
  await expect(table.getByText("Unavailable", { exact: true })).toHaveCount(2);
  await expect(table.getByText("$0.1235", { exact: true })).toHaveCount(0);
});

test("Post-mortem shows annual aggregates and metric sources even when accounts fail", async ({
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
  await expect(
    page.getByRole("link", { name: "[ Post-mortem ]", exact: true }),
  ).toHaveAttribute("aria-current", "page");
  const financials = page.locator(".annual-financials");
  await expect(
    financials.getByText("Illustrative weights", { exact: true }),
  ).toBeVisible();
  await expect(financials.getByText("-12.50%", { exact: true })).toBeVisible();
  await expect(
    financials.getByRole("row", { name: /^Gross margin/ }),
  ).toContainText("75%");
  await expect(
    financials.getByText("Not applicable to insurers", { exact: true }),
  ).toBeVisible();
  await expect(
    financials.getByRole("row", { name: /Net margin \(common shareholders\)/ }),
  ).toHaveCount(0);
  await expect(
    financials.getByRole("row", { name: /^Consolidated CFO margin/ }),
  ).toHaveCount(0);
  await expect(
    financials.getByRole("row", { name: /^FCF margin/ }),
  ).toContainText("100%");
  await expect(
    financials.getByText("Consolidated net margin", { exact: true }),
  ).toHaveCount(0);
  await expect(
    financials.getByText("FCF margin after cash PP&E capex", { exact: true }),
  ).toHaveCount(0);
  await expect(page.locator(".financial-company")).toHaveCount(0);
  await expect(page.locator(".financial-weights")).toHaveCount(0);
  const operating = financials.getByRole("row", { name: /^Operating margin/ });
  await operating.getByText("Source filings", { exact: true }).click();
  await expect(
    operating.getByRole("link", { name: "Filing 2026-02-01" }),
  ).toHaveAttribute("href", "https://example.org/annual-report");
  const fcf = financials.getByRole("row", {
    name: /^FCF margin/,
  });
  await fcf.getByText("Source filings", { exact: true }).click();
  await expect(
    fcf.getByText(
      "Mixed acquisition and capital-spending rows are excluded, not assumed zero.",
    ),
  ).toHaveCount(0);
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
    financials.getByRole("region", { name: "Weighted annual ratios" }),
  ).toBeVisible();
});

test("empty annual data offers retry without empty company sections", async ({
  page,
}) => {
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
    financials.getByRole("region", { name: "Weighted annual ratios" }),
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
      .getByRole("region", { name: "Weighted annual ratios" }),
  ).toBeVisible();
});
