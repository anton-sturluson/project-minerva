import { expect, test, type Page } from "@playwright/test";
import type { FinancialReport, PerShareComparison } from "../src/financialApi";

const main = "00000000-0000-4000-8000-000000000091";
const other = "00000000-0000-4000-8000-000000000092";

function report(accountId = main, year = 2026): FinancialReport {
  const comparison = (
    prior: string,
    change: string | null,
  ): PerShareComparison => ({
    prior_year: year - 1,
    prior_value: year === 2023 ? null : prior,
    status:
      year === 2023
        ? "unavailable"
        : change === null
          ? "not_meaningful"
          : "calculated",
    percent_change: year === 2023 ? null : change,
  });
  return {
    account_id: accountId,
    synthetic: false,
    calendar_year: year,
    holdings_date: `${year}-12-31`,
    api_status: accountId === other ? "unavailable" : "partial",
    market_value_snapshot: {
      holdings: [
        { issuer_key: "example:issuer", ticker: "EXM" },
        { issuer_key: "example:excluded", ticker: "OTH" },
      ],
    },
    companies: [
      {
        issuer_key: "example:issuer",
        ticker: "EXM",
        name: "Example Company",
        equity_weight: "0.75",
        financial_status: "eligible",
        per_share_metrics: {
          basic_eps: {
            status: "available",
            value: "2.34",
            method: "derived_ltm",
          },
          fcf_per_basic_share: { status: "available", value: "0.123456" },
        },
        per_share_comparisons: {
          basic_eps: comparison("2.00", "0.17"),
          fcf_per_basic_share: comparison(
            year === 2024 ? "-0.00321" : "0.15432",
            year === 2024 ? null : "-0.2",
          ),
        },
      },
      {
        issuer_key: "example:excluded",
        ticker: "OTH",
        name: "Other Example Company",
        equity_weight: "0.25",
        financial_status: "unavailable",
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
        value: year === 2023 ? "0.23" : "-0.125",
        coverage: "0.75",
        exclusions: [
          {
            issuer_key: "example:excluded",
            reason: "Annual operating figure not collected.",
          },
        ],
      },
      fcf_margin_after_disclosed_capex: {
        label: "FCF margin",
        value: "0.13",
        coverage: "1",
        exclusions: [],
      },
    },
    weighted_company_per_share: {
      weighted_company_eps: {
        label: "Weighted company EPS",
        value: "3.45",
        coverage: "1",
        exclusions: [],
        comparison: comparison("3.00", "0.15"),
      },
      weighted_company_fcf_per_share: {
        label: "Weighted company FCF/share",
        value: "0.317592",
        coverage: "1",
        exclusions: [],
        comparison: comparison("0.39699", "-0.2"),
      },
    },
  };
}

async function financialRoute(page: Page) {
  await page.route("**/api/accounts/*/financials?year=*", (route) => {
    const url = new URL(route.request().url());
    return route.fulfill({
      json: report(
        url.pathname.split("/")[3],
        Number(url.searchParams.get("year")),
      ),
    });
  });
}

test.beforeEach(async ({ page }) => {
  await page.route("**/api/accounts", (route) =>
    route.fulfill({
      json: [main, other].map((id, index) => ({
        id,
        name:
          index === 0
            ? "Synthetic Main Portfolio"
            : "Synthetic Other Portfolio",
        base_currency: "USD",
        created_at: "2023-01-01T00:00:00Z",
      })),
    }),
  );
  await page.route("**/api/accounts/*/ledger", (route) =>
    route.fulfill({
      json: {
        currency: "USD",
        balance: "1000",
        holdings: [],
        corrections: [],
        entries: [
          {
            id: 1,
            kind: "opening_cash",
            effective_date: "2023-01-02",
            amount: "1000",
            currency: "USD",
            note: "",
            security: null,
          },
        ],
      },
    }),
  );
  await page.route("**/api/accounts/*/performance", (route) =>
    route.fulfill({
      json: {
        attribution: [2025, 2026].map((year) => ({
          period: String(year),
          start: `${year - 1}-12-31`,
          end: `${year}-12-31`,
          return: ".12",
          contribution_total: ".12",
          gain: "650",
          stocks: [
            {
              security_id: "example",
              ticker: "EXM",
              exchange: "NYSE",
              contribution: ".12",
              gain: "650",
            },
          ],
        })),
      },
    }),
  );
});

test("selected portfolio financials lead contributors with one shared year and folded details", async ({
  page,
}) => {
  await financialRoute(page);
  await page.goto("/#post-mortem");
  await expect(page.getByLabel("Post-mortem year")).toHaveValue("2026");
  const financials = page.locator(".annual-financials");
  const summary = financials.getByRole("region", {
    name: "Portfolio-weighted metrics",
  });
  await expect(
    summary.getByRole("row", { name: /^Weighted company EPS/ }),
  ).toContainText("$3.5");
  await expect(
    summary.getByRole("row", { name: /^Weighted company FCF/ }),
  ).toContainText("$0.3");
  await expect(financials.getByText("-12.5%", { exact: true })).toBeVisible();
  await expect(page.locator(".financial-per-share-table")).toBeHidden();
  await page.getByText("Company details", { exact: true }).click();
  const table = page.getByRole("region", { name: "Company per-share figures" });
  await expect(table.getByRole("row", { name: /^EXM EPS/ })).toContainText(
    "$2.3",
  );
  await expect(table.getByRole("row", { name: /^EXM FCF/ })).toContainText(
    "$0.1",
  );
  await expect(
    financials.getByText(
      "1 Gross margin excludes OTH (25.0% weight; insurer).",
      { exact: true },
    ),
  ).toBeVisible();
  await expect(page.getByLabel("Financial year")).toHaveCount(0);
  await expect(
    page.getByText("Illustrative weights", { exact: true }),
  ).toHaveCount(0);
  await expect(
    financials.getByRole("columnheader", { name: /^(Coverage|Sources)$/ }),
  ).toHaveCount(0);
  expect(
    await page.evaluate(() => {
      const financials = document.querySelector(".annual-financials")!;
      const picker = document.querySelector(".portfolio-picker")!;
      const contributors = document.querySelector(".contribution-leaders")!;
      return (
        Boolean(
          picker.compareDocumentPosition(financials) &
          Node.DOCUMENT_POSITION_FOLLOWING,
        ) &&
        Boolean(
          financials.compareDocumentPosition(contributors) &
          Node.DOCUMENT_POSITION_FOLLOWING,
        )
      );
    }),
  ).toBe(true);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({
    path: test.info().outputPath("financials.png"),
    fullPage: true,
  });
});

test("shared year updates current, prior and changes; all history withholds annual figures", async ({
  page,
}) => {
  const requested: string[] = [];
  page.on("request", (request) => {
    if (request.url().includes("/financials?")) requested.push(request.url());
  });
  await financialRoute(page);
  await page.goto("/#post-mortem");
  const summary = page.getByRole("region", {
    name: "Portfolio-weighted metrics",
  });
  const eps = summary.getByRole("row", { name: /^Weighted company EPS/ });
  await expect(eps).toContainText("15.0%");
  await expect(
    summary.getByRole("columnheader", { name: "2025", exact: true }),
  ).toBeVisible();
  await page.getByLabel("Post-mortem year").selectOption("2024");
  await page.getByText("Company details", { exact: true }).click();
  await expect(
    page
      .getByRole("region", { name: "Company per-share figures" })
      .getByRole("row", { name: /^EXM FCF/ }),
  ).toContainText("N/M");
  await page.getByLabel("Post-mortem year").selectOption("2023");
  await expect(
    summary.getByRole("columnheader", { name: "2022", exact: true }),
  ).toBeVisible();
  await expect(eps.getByText("Unavailable", { exact: true })).toHaveCount(2);
  const count = requested.length;
  await page.getByLabel("Post-mortem year").selectOption("all");
  await expect(page.locator(".annual-financials")).toContainText(
    "Choose a year to view portfolio financials.",
  );
  await expect(summary).toHaveCount(0);
  expect(requested.length).toBe(count);
});

test("prior headline matches the prior portfolio and names its own omitted holdings", async ({
  page,
}) => {
  await page.route("**/api/accounts/*/financials?year=*", (route) => {
    const year = Number(
      new URL(route.request().url()).searchParams.get("year"),
    );
    const data = report(main, year);
    const eps = data.weighted_company_per_share!.weighted_company_eps;
    const fcf = data.weighted_company_per_share!.weighted_company_fcf_per_share;
    if (year === 2026) {
      eps.comparison = {
        ...eps.comparison!,
        prior_value: null,
        status: "unavailable",
        percent_change: null,
        reason: "Prior market prices unavailable",
      };
    } else if (year === 2025) {
      data.companies.push({
        issuer_key: "example:zero",
        ticker: "ZERO",
        name: "Pre-revenue company",
        equity_weight: "0.05",
        financial_status: "eligible",
      });
      data.companies[0].equity_weight = "0.70";
      data.weighted_ratios.fcf_margin_after_disclosed_capex.exclusions = [
        {
          issuer_key: "example:zero",
          reason: "Revenue denominator is zero or negative",
        },
      ];
      eps.comparison = {
        ...eps.comparison!,
        prior_value: "7.25",
        percent_change: "-0.524137931",
      };
      fcf.comparison = {
        ...fcf.comparison!,
        prior_value: "1.75",
        percent_change: "-0.818518857",
      };
      eps.comparison.exclusions = [
        {
          ticker: "OLD",
          issuer_key: "example:old",
          equity_weight: "0.4",
          reason: "Prior EPS unavailable",
        },
      ];
    } else if (year === 2024) {
      data.companies = [
        {
          issuer_key: "example:previous",
          ticker: "PREV",
          name: "Previous holding",
          equity_weight: "0.6",
          financial_status: "eligible",
        },
      ];
      eps.value = "7.25";
      fcf.value = "1.75";
    }
    return route.fulfill({ json: data });
  });
  await page.goto("/#post-mortem");
  const summary = page.getByRole("region", {
    name: "Portfolio-weighted metrics",
  });
  const eps = summary.getByRole("row", { name: /^Weighted company EPS/ });
  await expect(eps.getByRole("cell").nth(0)).toHaveText("$3.5");
  await expect(eps.getByRole("cell").nth(1)).toHaveText("Unavailable");
  await page.getByLabel("Post-mortem year").selectOption("2025");
  const fcf = summary.getByRole("row", { name: /^Weighted company FCF/ });
  await expect(eps.getByRole("cell").nth(1)).toHaveText("$7.34");
  await expect(fcf.getByRole("cell").nth(1)).toHaveText("$1.8");
  await expect(
    page.getByText(
      "4 2024 Weighted company EPS excludes OLD (40.0% weight; data unavailable).",
      { exact: true },
    ),
  ).toBeVisible();
  await expect(
    page.getByText(
      "3 FCF margin excludes ZERO (5.0% weight; zero or negative revenue).",
      {
        exact: true,
      },
    ),
  ).toBeVisible();
  const notes = page.locator(".annual-financials .form-note");
  await expect(notes.locator("sup")).toHaveText(["1", "2", "3", "4"]);
  await expect(
    summary.getByRole("rowheader", { name: /^FCF margin/ }),
  ).toHaveAttribute(
    "aria-describedby",
    "fcf_margin_after_disclosed_capex-exclusions",
  );
  await expect(eps.getByRole("cell").nth(1)).toHaveAttribute(
    "aria-describedby",
    "weighted_company_eps-prior-exclusions",
  );
  await expect(eps.getByRole("cell").nth(2)).toHaveText("-52.4%");
  await page.screenshot({
    path: test.info().outputPath("prior-omissions.png"),
    fullPage: true,
  });
  await page.getByLabel("Post-mortem year").selectOption("2024");
  await expect(eps.getByRole("cell").nth(0)).toHaveText("$7.3");
  await expect(fcf.getByRole("cell").nth(0)).toHaveText("$1.8");
  await expect(
    page.getByText(/2024 Weighted company EPS excludes OLD/),
  ).toHaveCount(0);
});

test("financial table remains independent when attribution fails and retries its own error", async ({
  page,
}) => {
  await page.route("**/api/accounts/*/performance", (route) =>
    route.fulfill({
      status: 503,
      json: { detail: "Synthetic attribution unavailable" },
    }),
  );
  let fail = true;
  await page.route("**/api/accounts/*/financials?year=*", (route) =>
    fail
      ? route.fulfill({
          status: 503,
          json: { detail: "Private connection details" },
        })
      : route.fulfill({ json: report() }),
  );
  await page.goto("/#post-mortem");
  await expect(page.getByLabel("Post-mortem year")).toBeVisible();
  const financials = page.locator(".annual-financials");
  await expect(financials.getByRole("alert")).toContainText(
    "Could not load annual figures.",
  );
  await expect(page.getByText("Private connection details")).toHaveCount(0);
  fail = false;
  await financials.getByRole("button", { name: "Retry financials" }).click();
  await expect(
    financials.getByRole("region", { name: "Portfolio-weighted metrics" }),
  ).toBeVisible();
  await expect(
    page.getByText("Synthetic attribution unavailable"),
  ).toBeVisible();
});

test("portfolio switch clears old figures and never falls back for unavailable accounts", async ({
  page,
}) => {
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  let requested!: () => void;
  const waiting = new Promise<void>((resolve) => {
    requested = resolve;
  });
  await page.route("**/api/accounts/*/financials?year=*", async (route) => {
    const url = new URL(route.request().url());
    const id = url.pathname.split("/")[3];
    const year = Number(url.searchParams.get("year"));
    if (id === main && year === 2024) {
      requested();
      await gate;
    }
    await route.fulfill({ json: report(id, year) });
  });
  await page.goto("/#post-mortem");
  await expect(
    page.getByRole("region", { name: "Portfolio-weighted metrics" }),
  ).toBeVisible();
  await page.getByLabel("Post-mortem year").selectOption("2024");
  await waiting;
  await page.getByLabel("Portfolio", { exact: true }).selectOption(other);
  const financials = page.locator(".annual-financials");
  await expect(financials).toContainText("Table unavailable.");
  const olderResponse = page.waitForResponse(
    (response) =>
      response.url().includes(main) && response.url().includes("year=2024"),
  );
  release();
  await olderResponse;
  await expect(
    financials.getByRole("region", { name: "Portfolio-weighted metrics" }),
  ).toHaveCount(0);
  await expect(page.getByLabel("Post-mortem year")).toHaveValue("2026");
});

for (const mismatch of ["account", "year", "synthetic"] as const) {
  test(`mismatched ${mismatch} response cannot display another report`, async ({
    page,
  }) => {
    await page.route("**/api/accounts/*/financials?year=*", (route) => {
      const data = report();
      if (mismatch === "account") data.account_id = other;
      if (mismatch === "year") data.calendar_year = 2025;
      if (mismatch === "synthetic") data.synthetic = true;
      return route.fulfill({ json: data });
    });
    await page.goto("/#post-mortem");
    const financials = page.locator(".annual-financials");
    await expect(financials.getByRole("alert")).toBeVisible();
    await expect(
      financials.getByRole("region", { name: "Portfolio-weighted metrics" }),
    ).toHaveCount(0);
  });
}
