import { expect, test } from "@playwright/test";
import type { FinancialReport } from "../src/financialApi";

function report(year = 2025): FinancialReport {
  return {
    synthetic: true,
    calendar_year: year,
    holdings_date: `${year}-12-31`,
    api_status: "partial",
    market_value_snapshot: {
      holdings: ["AAA", "BBB", "CCC"].map((ticker) => ({
        issuer_key: ticker,
        ticker,
      })),
    },
    companies: ["AAA", "BBB", "CCC"].map((ticker, index) => ({
      issuer_key: ticker,
      equity_weight: ["0.60", "0.25", "0.15"][index],
      financial_status: "eligible",
      reason: null,
      profile: {
        issuer: { name: `Synthetic ${ticker} Company` },
        period: {
          fiscal_label: `FY${year}`,
          start: `${year}-01-01`,
          end: `${year}-12-31`,
        },
        sources: [
          {
            source_id: "filing",
            url: "https://example.org/annual-report",
            published_on: `${year + 1}-02-01`,
          },
        ],
        facts: {
          revenue: {
            status: "reported",
            value: String(year * 1000),
            source_id: "filing",
          },
          net_income_common: {
            status: "reported",
            value: "100000",
            source_id: "filing",
          },
          operating_cash_flow: {
            status: "reported",
            value: "50000",
            source_id: "filing",
          },
          basic_eps: {
            status: "reported",
            value: "1.25",
            source_id: "filing",
            share_basis: {
              classes: ["class_a"],
              split_adjusted_through: `${year}-12-31`,
            },
          },
          diluted_eps: {
            status: "reported",
            value: "1.10",
            source_id: "filing",
            share_basis: {
              classes: ["class_a"],
              split_adjusted_through: `${year}-12-31`,
            },
          },
          basic_weighted_average_shares: {
            status: "reported",
            value: "100000",
            share_basis: {
              classes: ["class_a", "class_b"],
              split_adjusted_through: `${year}-12-31`,
              equivalence_note: "Verified common-class economic equivalence.",
            },
          },
          cash_capex_ppe: {
            status: "unavailable",
            reason: "Cash capital spending categories cannot be separated.",
            source_id: "filing",
          },
        },
        calculations: {
          allocated_cfo_per_basic_share: {
            status: "calculated",
            value: "0.50",
            inputs: [{ source_id: "filing" }],
          },
          fcf_after_ppe: {
            status: "unavailable",
            reason: "Missing/applicability inputs: cash_capex_ppe",
            inputs: [{ source_id: "filing" }],
          },
        },
      },
    })),
    weighted_ratios: {
      operating_margin: {
        label: "Operating margin",
        status: "calculated",
        value: "-0.125",
        coverage: "0.75",
        exclusions: [
          {
            issuer_key: "BBB",
            reason: "Annual operating figure not collected.",
          },
        ],
      },
      fcf_margin_after_ppe: {
        label: "FCF margin after cash PP&E capex",
        status: "unavailable",
        value: null,
        coverage: "0",
        exclusions: [
          {
            issuer_key: "AAA",
            reason: "Missing/applicability inputs: cash_capex_ppe",
          },
        ],
      },
    },
  };
}

test("annual figures show illustrative weights, class scope, coverage and sources", async ({
  page,
}) => {
  await page.route("**/api/financials?year=*", (route) =>
    route.fulfill({ json: report() }),
  );
  await page.goto("/#financials");
  await expect(
    page.getByRole("heading", { name: "Annual financials" }),
  ).toBeVisible();
  await expect(
    page.getByText("Illustrative weights — not your portfolio."),
  ).toBeVisible();
  await expect(page.locator(".financial-weights")).toHaveText(
    "AAA: 60% · BBB: 25% · CCC: 15%",
  );
  const ratios = page.getByRole("region", { name: "Weighted annual ratios" });
  await expect(ratios.getByText("-12.50%", { exact: true })).toBeVisible();
  await expect(ratios.getByText("75%", { exact: true })).toBeVisible();
  await expect(
    ratios.getByText("BBB: Annual operating figure not collected"),
  ).toBeVisible();
  const company = page.getByRole("region", {
    name: "Synthetic AAA Company financial figures",
  });
  await expect(
    company.getByRole("row", { name: /Common earnings/ }),
  ).toContainText("100,000");
  await expect(company.getByRole("row", { name: /Diluted EPS/ })).toContainText(
    "Class A · split basis through 2025-12-31",
  );
  await expect(
    company.getByRole("row", { name: /Allocated CFO per basic share/ }),
  ).toContainText("Verified common-class economic equivalence");
  await expect(
    company.getByRole("row", { name: /^Cash PP&E capex/ }),
  ).toContainText("Cash capital spending categories cannot be separated");
  await expect(
    company.getByRole("link", { name: "Filing 2026-02-01" }).first(),
  ).toHaveAttribute("href", "https://example.org/annual-report");
  await expect(page.getByLabel("Portfolio", { exact: true })).toHaveCount(0);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});

test("loading, transport failure and retry recover without exposing setup details", async ({
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
  await page.goto("/#financials");
  await expect(page.getByRole("status")).toHaveText(
    "Loading FY2025 financials…",
  );
  release();
  await expect(page.getByRole("alert")).toContainText(
    "Could not load annual figures.",
  );
  await expect(
    page.getByText("Private database configuration details"),
  ).toHaveCount(0);
  fail = false;
  await page.getByRole("button", { name: "Retry financials" }).click();
  await expect(
    page.getByRole("heading", { name: "Weighted ratios" }),
  ).toBeVisible();
});

test("empty annual data uses a clear retry state", async ({ page }) => {
  const empty = report();
  empty.api_status = "unavailable";
  empty.companies = [];
  await page.route("**/api/financials?year=*", (route) =>
    route.fulfill({ json: empty }),
  );
  await page.goto("/#financials");
  await expect(page.getByRole("status")).toContainText(
    "Annual figures aren't available yet.",
  );
  await expect(
    page.getByRole("button", { name: "Retry financials" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Weighted ratios" }),
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
  await page.route("**/api/financials?year=*", async (route) => {
    const year = Number(
      new URL(route.request().url()).searchParams.get("year"),
    );
    if (year === 2025) await gate;
    await route.fulfill({ json: report(year) });
    if (year === 2025) oldFinished();
  });
  await page.goto("/#financials");
  await page.getByLabel("Financial year").selectOption("2023");
  await expect(
    page.getByText(
      "Year-end weights: 2023-12-31. Financial periods end within 2023.",
    ),
  ).toBeVisible();
  release();
  await finished;
  await expect(
    page.getByText("FY2023 · 2023-01-01 through 2023-12-31 · USD"),
  ).toHaveCount(3);
  await expect(
    page.getByText("FY2025 · 2025-01-01 through 2025-12-31 · USD"),
  ).toHaveCount(0);
});
