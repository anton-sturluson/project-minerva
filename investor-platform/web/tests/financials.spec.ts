import { expect, test, type Page } from "@playwright/test";
import type {
  FinancialReport,
  FinancialComparison,
} from "../src/financials/financialApi";

const main = "00000000-0000-4000-8000-000000000091";
const other = "00000000-0000-4000-8000-000000000092";

function report(accountId = main, year = 2026): FinancialReport {
  const comparison = (
    prior: string,
    change: string | null,
  ): FinancialComparison => ({
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
        exchange: "NYSE",
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
        exchange: "NYSE",
        name: "Other Example Company",
        equity_weight: "0.25",
        financial_status: "unavailable",
      },
    ],
    weighted_ratios: {
      gross_margin: {
        label: "Gross margin",
        comparison: comparison("0.32", "0.25"),
        value: "0.40",
        coverage: "0.75",
        exclusions: [
          {
            issuer_key: "example:excluded",
            ticker: "OTH",
            equity_weight: "0.25",
            reason: "Gross margin is not applicable for an insurer.",
          },
        ],
      },
      operating_margin: {
        label: "Operating margin",
        comparison: comparison("-0.10", null),
        value: year === 2023 ? "0.23" : "-0.125",
        coverage: "0.75",
        exclusions: [
          {
            issuer_key: "example:excluded",
            ticker: "OTH",
            equity_weight: "0.25",
            reason: "Annual operating figure not collected.",
          },
        ],
      },
      fcf_margin_after_disclosed_capex: {
        label: "FCF margin",
        comparison: comparison("0.10", "0.3"),
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
  await page.clock.install({ time: new Date("2026-10-17T16:00:00Z") });
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
  await expect(
    summary
      .getByRole("row", { name: /^Operating margin/ })
      .getByRole("cell")
      .nth(0),
  ).toHaveText("-12.5%2");
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

test("zero figures stay available without zero-revenue notes", async ({
  page,
}) => {
  await page.route("**/api/accounts/*/financials?year=*", (route) => {
    const data = report();
    data.weighted_ratios.fcf_margin_after_disclosed_capex.value = "0";
    data.weighted_ratios.fcf_margin_after_disclosed_capex.conventions = [
      { issuer_key: "example:issuer", ticker: "EXM" },
    ];
    data.weighted_ratios.operating_margin.conventions = [
      { issuer_key: "example:issuer", ticker: "EXM" },
    ];
    data.weighted_company_per_share!.weighted_company_eps.value = "0";
    data.companies[0].per_share_metrics!.basic_eps = {
      status: "available",
      value: "2.34",
      eps_basis: "diluted",
    };
    return route.fulfill({ json: data });
  });
  await page.goto("/#post-mortem");
  const summary = page.getByRole("region", {
    name: "Portfolio-weighted metrics",
  });
  await expect(
    summary
      .getByRole("row", { name: /^FCF margin/ })
      .getByRole("cell")
      .nth(0),
  ).toHaveText("0.0%");
  await expect(
    summary
      .getByRole("row", { name: /^Weighted company EPS/ })
      .getByRole("cell")
      .nth(0),
  ).toHaveText("$0.0");
  await expect(page.getByText(/included at 0%|no revenue/i)).toHaveCount(0);
  await expect(
    summary.getByRole("row", { name: /^FCF margin/ }).locator("sup"),
  ).toHaveCount(0);
  await expect(page.getByText(/Operating margin excludes OTH/)).toBeVisible();
  await page.getByText("Company details", { exact: true }).click();
  await expect(
    page.getByRole("cell", { name: "EPS (diluted)", exact: true }),
  ).toBeVisible();
});

test("issuer non-reporting differs from missing data and cash share basis is explicit", async ({
  page,
}) => {
  await page.route("**/api/accounts/*/financials?year=*", (route) => {
    const data = report();
    const reason =
      "EPS not reported: issuer does not present earnings per share";
    data.companies[1].financial_status = "eligible";
    data.companies[1].per_share_metrics = {
      basic_eps: { status: "unavailable", value: null, reason },
    };
    data.companies[1].per_share_comparisons = {
      basic_eps: {
        prior_year: 2025,
        prior_value: null,
        status: "unavailable",
        percent_change: null,
        reason,
      },
    };
    data.companies[0].per_share_metrics!.fcf_per_basic_share.share_denominator_basis =
      "diluted_weighted_average";
    data.weighted_company_per_share!.weighted_company_eps.exclusions = [
      {
        issuer_key: "example:excluded",
        ticker: "OTH",
        equity_weight: "0.25",
        reason,
      },
    ];
    return route.fulfill({ json: data });
  });
  await page.goto("/#post-mortem");
  await expect(
    page.getByText(
      "3 Weighted company EPS excludes OTH (25.0% weight; not reported).",
      { exact: true },
    ),
  ).toBeVisible();
  await page.getByText("Company details", { exact: true }).click();
  const details = page.getByRole("region", {
    name: "Company per-share figures",
  });
  const eps = details
    .getByRole("row")
    .filter({ hasText: "OTH" })
    .filter({ hasText: "EPS (basic)" });
  await expect(
    eps.getByRole("cell", { name: "Not reported", exact: true }),
  ).toHaveCount(2);
  await expect(
    details.getByRole("cell", {
      name: "FCF/share (diluted shares)",
      exact: true,
    }),
  ).toBeVisible();
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
        exchange: "NYSE",
        name: "Pre-revenue company",
        equity_weight: "0.05",
        financial_status: "eligible",
      });
      data.companies[0].equity_weight = "0.70";
      data.weighted_ratios.fcf_margin_after_disclosed_capex.exclusions = [
        {
          issuer_key: "example:zero",
          ticker: "ZERO",
          equity_weight: "0.05",
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
          exchange: "NYSE",
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
    summary
      .getByRole("row", { name: /^FCF margin/ })
      .getByRole("cell")
      .nth(0),
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

test("gross margin keeps a numbered cost-basis note without exclusions", async ({
  page,
}) => {
  await page.route("**/api/accounts/*/financials?year=*", (route) => {
    const data = report();
    data.weighted_ratios.gross_margin.exclusions = [];
    data.weighted_ratios.gross_margin.basis_notes = [
      {
        ticker: "EXM",
        note: "excludes separately reported depreciation and amortization",
      },
    ];
    return route.fulfill({ json: data });
  });
  await page.goto("/#post-mortem");
  await expect(
    page.getByText(
      "1 Gross margin: EXM: excludes separately reported depreciation and amortization.",
      { exact: true },
    ),
  ).toBeVisible();
  const gross = page
    .getByRole("region", { name: "Portfolio-weighted metrics", exact: true })
    .getByRole("row")
    .filter({ hasText: "Gross margin" });
  await expect(gross.getByRole("cell").nth(0)).toHaveText("40.0%1");
  await expect(gross.getByRole("cell").nth(0).locator("sup")).toHaveText("1");
  await expect(gross.getByRole("rowheader").locator("sup")).toHaveCount(0);
});

test("all prior margin cells show the actual previous portfolio and retain its disclosures", async ({
  page,
}) => {
  await page.route("**/api/accounts/*/financials?year=*", (route) => {
    const year = Number(
      new URL(route.request().url()).searchParams.get("year"),
    );
    const data = report(main, year);
    const prior = {
      gross_margin: "0.25",
      operating_margin: "0.10",
      fcf_margin_after_disclosed_capex: "0.08",
    };
    if (year === 2026) {
      for (const [key, value, change] of [
        ["gross_margin", "0.40", "0.6"],
        ["operating_margin", "0.20", "1"],
        ["fcf_margin_after_disclosed_capex", "0.12", "0.5"],
      ]) {
        data.weighted_ratios[key].value = value;
        data.weighted_ratios[key].comparison = {
          prior_year: 2025,
          prior_value: prior[key as keyof typeof prior],
          status: "calculated",
          percent_change: change,
        };
      }
      data.weighted_ratios.gross_margin.comparison!.basis_notes = [
        {
          ticker: "OLD",
          note: "excludes separately reported depreciation and amortization",
        },
      ];
      data.weighted_ratios.fcf_margin_after_disclosed_capex.comparison!.exclusions =
        [
          {
            issuer_key: "example:sold",
            ticker: "SOLD",
            equity_weight: "0.2",
            reason: "Prior source unavailable",
          },
        ];
    } else if (year === 2025) {
      data.companies = [
        {
          issuer_key: "example:old",
          ticker: "OLD",
          exchange: "NYSE",
          name: "Previous holding",
          equity_weight: "1",
          financial_status: "eligible",
        },
      ];
      for (const [key, value] of Object.entries(prior))
        data.weighted_ratios[key].value = value;
    }
    return route.fulfill({ json: data });
  });
  await page.goto("/#post-mortem");
  const summary = page.getByRole("region", {
    name: "Portfolio-weighted metrics",
  });
  const expected = [
    ["Gross margin", "40.0%1", "25.0%3", "60.0%"],
    ["Operating margin", "20.0%2", "10.0%", "100.0%"],
    ["FCF margin", "12.0%", "8.0%4", "50.0%"],
  ];
  for (const [label, current, prior, change] of expected) {
    const row = summary.getByRole("row", { name: new RegExp(`^${label}`) });
    await expect(row.getByRole("cell")).toHaveText([current, prior, change]);
  }
  await expect(
    page.getByText(
      "3 2025 Gross margin: OLD: excludes separately reported depreciation and amortization.",
      { exact: true },
    ),
  ).toBeVisible();
  await expect(
    page.getByText(
      "4 2025 FCF margin excludes SOLD (20.0% weight; data unavailable).",
      { exact: true },
    ),
  ).toBeVisible();
  await expect(
    summary
      .getByRole("row", { name: /^Gross margin/ })
      .getByRole("cell")
      .nth(1),
  ).toHaveAttribute("aria-describedby", "gross_margin-prior-exclusions");
  await page.getByLabel("Post-mortem year").selectOption("2025");
  for (const [label, value] of [
    ["Gross margin", "25.0%1"],
    ["Operating margin", "10.0%2"],
    ["FCF margin", "8.0%"],
  ]) {
    const row = summary.getByRole("row", { name: new RegExp(`^${label}`) });
    await expect(row.getByRole("cell").nth(0)).toHaveText(value);
  }
  await page.getByLabel("Post-mortem year").selectOption("2024");
  await expect(
    summary
      .getByRole("row", { name: /^Operating margin/ })
      .getByRole("cell")
      .nth(2),
  ).toHaveText("N/M");
  await page.getByLabel("Post-mortem year").selectOption("2023");
  for (const [label] of expected) {
    const row = summary.getByRole("row", { name: new RegExp(`^${label}`) });
    await expect(row.getByRole("cell").nth(1)).toHaveText("Unavailable");
    await expect(row.getByRole("cell").nth(2)).toHaveText("Unavailable");
  }
});

test("same-issuer listings keep their own omission weights and detail rows", async ({
  page,
}) => {
  const duplicateKeys: string[] = [];
  page.on("console", (message) => {
    if (
      message.type() === "error" &&
      /same key|unique.*key/i.test(message.text())
    )
      duplicateKeys.push(message.text());
  });
  await page.route("**/api/accounts/*/financials?year=*", (route) => {
    const year = Number(
      new URL(route.request().url()).searchParams.get("year"),
    );
    const data = report(main, year);
    const company = { ...data.companies[0], issuer_key: "example:shared" };
    data.companies = [
      { ...company, ticker: "CLASSA", exchange: "NYSE", equity_weight: "0.8" },
      {
        ...company,
        ticker: "CLASSB",
        exchange: "NASDAQ",
        equity_weight: "0.2",
      },
    ].map((listing, index) => ({
      ...listing,
      per_share_metrics: {
        ...company.per_share_metrics,
        basic_eps: { status: "available", value: String(index * 2 + 1) },
      },
      per_share_comparisons: {
        ...company.per_share_comparisons,
        basic_eps: {
          prior_year: year - 1,
          prior_value: String(index * 2 + 1),
          status: "calculated",
          percent_change: "0",
        },
      },
    }));
    if (year === 2025) data.companies.reverse();
    data.market_value_snapshot = {
      holdings: data.companies.map(({ issuer_key, ticker }) => ({
        issuer_key,
        ticker,
      })),
    };
    data.weighted_ratios.gross_margin.exclusions = [
      {
        issuer_key: "example:shared",
        ticker: "CLASSB",
        equity_weight: "0.2",
        reason: "Gross margin source unavailable",
      },
    ];
    data.weighted_ratios.operating_margin.exclusions = [];
    return route.fulfill({ json: data });
  });
  await page.goto("/#post-mortem");
  await expect(
    page.getByText(
      "1 Gross margin excludes CLASSB (20.0% weight; data unavailable).",
      { exact: true },
    ),
  ).toBeVisible();
  await expect(page.getByText(/Gross margin excludes CLASSA/)).toHaveCount(0);
  await expect(page.locator(".annual-financials details")).not.toHaveAttribute(
    "open",
  );
  await page.getByText("Company details", { exact: true }).click();
  const details = page.getByRole("region", {
    name: "Company per-share figures",
  });
  for (const [ticker, value] of [
    ["CLASSA", "$1.0"],
    ["CLASSB", "$3.0"],
  ]) {
    const row = details
      .getByRole("row")
      .filter({
        has: page.getByRole("rowheader", { name: ticker, exact: true }),
      })
      .filter({ hasText: "EPS (basic)" });
    await expect(row.getByRole("cell")).toHaveText([
      "EPS (basic)",
      value,
      value,
      "0.0%",
    ]);
  }
  await page.getByLabel("Post-mortem year").selectOption("2025");
  await expect(
    page.getByText(
      "1 Gross margin excludes CLASSB (20.0% weight; data unavailable).",
      { exact: true },
    ),
  ).toBeVisible();
  await expect(page.locator(".annual-financials details")).not.toHaveAttribute(
    "open",
  );
  await page.getByText("Company details", { exact: true }).click();
  for (const [ticker, value] of [
    ["CLASSA", "$1.0"],
    ["CLASSB", "$3.0"],
  ]) {
    const row = details
      .getByRole("row")
      .filter({
        has: page.getByRole("rowheader", { name: ticker, exact: true }),
      })
      .filter({ hasText: "EPS (basic)" });
    await expect(row.getByRole("cell")).toHaveText([
      "EPS (basic)",
      value,
      value,
      "0.0%",
    ]);
  }
  expect(duplicateKeys).toEqual([]);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({
    path: test.info().outputPath("same-issuer-financials.png"),
    fullPage: true,
  });
});

test("financials disclose the holdings cutoff and linked current and prior filing periods", async ({
  page,
}) => {
  await page.route("**/financials?year=*", (route) => {
    const data = report();
    data.holdings_date = "2026-10-16";
    data.publication_policy =
      "Retrospective: reviewed annual publications; no publication-date cutoff";
    data.companies[0].period = {
      start: "2025-07-01",
      end: "2026-06-30",
      fiscal_label: "FY2026",
    };
    data.companies[0].prior_period = {
      start: "2024-07-01",
      end: "2025-06-30",
      fiscal_label: "FY2025",
    };
    data.companies[0].source_urls = [
      "https://example.com/filings/exm-2026",
      "https://example.com/filings/exm-2025",
    ];
    return route.fulfill({ json: data });
  });
  await page.goto("/#post-mortem");
  await expect(page.getByText(/Holdings as of 2026-10-16/)).toBeVisible();
  await expect(
    page.getByText(/Retrospective figures; publication dates/),
  ).toBeVisible();
  await page.getByText("Company details", { exact: true }).click();
  const sources = page.getByRole("region", {
    name: "Financial sources and periods",
  });
  await expect(sources).toContainText(
    "Current period: 2025-07-01 through 2026-06-30 (FY2026)",
  );
  await expect(sources).toContainText(
    "Prior period: 2024-07-01 through 2025-06-30 (FY2025)",
  );
  await expect(
    sources.getByRole("link", { name: "EXM filing source 1" }),
  ).toHaveAttribute("href", "https://example.com/filings/exm-2026");
  await expect(
    sources.getByRole("link", { name: "EXM filing source 2" }),
  ).toHaveAttribute("href", "https://example.com/filings/exm-2025");
  await expect(sources).toContainText("No linked filing source available.");
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});

test("a valid cold financial request can finish after the ordinary API deadline", async ({
  page,
}) => {
  await page.route("**/financials?year=*", async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 9_000));
    await route.fulfill({ json: report() });
  });
  await page.goto("/#post-mortem");
  await expect(
    page.getByRole("region", { name: "Portfolio-weighted metrics" }),
  ).toBeVisible({ timeout: 15_000 });
  await expect(
    page.locator(".annual-financials").getByRole("alert"),
  ).toHaveCount(0);
});
