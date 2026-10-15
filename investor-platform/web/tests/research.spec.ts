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
  aum_usd: "100000000",
  aum_as_of: "2026-01-01",
  aum_source_url: "https://example.com/aum",
  aum_measurement: "firm_aum",
  eligibility: {
    status: "eligible",
    minimum_aum_usd: "50000000",
    reason: null,
  },
  portfolio_company_count: 5,
  portfolio_company_count_quarter: "2026-06-30",
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
      cusip: "123456780",
      issuer: "Example New Cloud",
      security_class: "COM",
      put_call: "",
      share_type: "SH",
      kind: "new",
      category: "increased",
      previous_quantity: "0",
      current_quantity: "300",
      quantity_change: "300",
      current_value_usd: "30000",
      value_change_usd: "30000",
      current_weight: "0.30",
      weight_change: "0.30",
    },
    {
      cusip: "123456789",
      issuer: "Example Software",
      security_class: "COM",
      put_call: "",
      share_type: "SH",
      kind: "increased",
      category: "increased",
      previous_quantity: "100",
      current_quantity: "125",
      quantity_change: "25",
      current_value_usd: "12500",
      value_change_usd: "4500",
      current_weight: "0.125",
      weight_change: "0.045",
    },
    {
      cusip: "123456781",
      issuer: "Example Largest Reduction",
      security_class: "COM",
      put_call: "",
      share_type: "SH",
      kind: "decreased",
      category: "decreased",
      previous_quantity: "1000",
      current_quantity: "100",
      quantity_change: "-900",
      current_value_usd: "10000",
      value_change_usd: "-80000",
      current_weight: "0.10",
      weight_change: "-0.8",
    },
    {
      cusip: "123456782",
      issuer: "Example Exit",
      security_class: "COM",
      put_call: "",
      share_type: "SH",
      kind: "exited",
      category: "decreased",
      previous_quantity: "20",
      current_quantity: "0",
      quantity_change: "-20",
      current_value_usd: "0",
      value_change_usd: "-25000",
      current_weight: "0",
      weight_change: "-0.25",
    },
    {
      cusip: "123456783",
      issuer: "Example Smaller Reduction",
      security_class: "COM",
      put_call: "",
      share_type: "SH",
      kind: "decreased",
      category: "decreased",
      previous_quantity: "90",
      current_quantity: "80",
      quantity_change: "-10",
      current_value_usd: "8000",
      value_change_usd: "-1000",
      current_weight: "0.08",
      weight_change: "-0.01",
    },
    {
      cusip: "123456784",
      issuer: "Example Unchanged Shares",
      security_class: "COM",
      put_call: "",
      share_type: "SH",
      kind: "unchanged",
      category: "unchanged",
      previous_quantity: "10",
      current_quantity: "10",
      quantity_change: "0",
      current_value_usd: "39500",
      value_change_usd: "500",
      current_weight: "0.395",
      weight_change: "0.005",
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
  const increased = page.getByRole("region", {
    name: "Quantity increased positions",
    exact: true,
  });
  const decreased = page.getByRole("region", {
    name: "Quantity decreased positions",
    exact: true,
  });
  const unchanged = page.getByRole("region", {
    name: "Quantity unchanged positions",
    exact: true,
  });
  await expect(increased.locator("tbody tr")).toHaveCount(2);
  await expect(increased.locator("tbody tr").nth(0)).toContainText(
    "Example New Cloud",
  );
  await expect(increased.locator("tbody tr").nth(0)).toContainText(
    "New position",
  );
  await expect(increased.locator("tbody tr").nth(0)).toContainText("+$30K");
  await expect(increased.locator("tbody tr").nth(0)).toContainText("30.00%");
  await expect(increased.locator("tbody tr").nth(1)).toContainText(
    "Example Software",
  );
  await expect(increased.locator("tbody tr").nth(1)).toContainText(
    "100 → 125 SH",
  );
  await expect(increased.locator("tbody tr").nth(1)).toContainText("$12K");
  await expect(increased.locator("tbody tr").nth(1)).toContainText("12.50%");
  await expect(decreased.locator("tbody tr")).toHaveCount(3);
  await expect(decreased.locator("tbody tr").nth(0)).toContainText(
    "Example Largest Reduction",
  );
  await expect(decreased.locator("tbody tr").nth(0)).toContainText("-$80K");
  await expect(decreased.locator("tbody tr").nth(1)).toContainText(
    "Example Exit",
  );
  await expect(decreased.locator("tbody tr").nth(1)).toContainText("Exited");
  await expect(decreased.locator("tbody tr").nth(1)).toContainText("0.00%");
  await expect(decreased.locator("tbody tr").nth(2)).toContainText(
    "Example Smaller Reduction",
  );
  await expect(unchanged.locator("tbody tr")).toHaveCount(1);
  await expect(unchanged.locator("tbody tr").nth(0)).toContainText(
    "Example Unchanged Shares",
  );
  await expect(unchanged.locator("tbody tr").nth(0)).toContainText("+$0.5K");
  await expect(unchanged.locator("tbody tr").nth(0)).toContainText(
    "10 → 10 SH",
  );
  await expect(page.getByText(/Largest absolute reported/)).toHaveCount(0);
  await expect(
    page.getByText(/Reported position changes, inferred/),
  ).toHaveCount(0);
  await expect(page.getByText(/quarters loaded/)).toHaveCount(0);
  await expect(page.getByText("Portfolio companies: 5")).toBeVisible();
  await expect(increased.locator("tbody tr").nth(0)).toContainText("+30.00 pp");
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
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

test("verified AUM is the default and candidates retain explicit status and history", async ({
  page,
}) => {
  const below = {
    ...manager,
    slug: "small-manager",
    name: "Example Small Partnership",
    aum_usd: "49000000",
    eligibility: {
      status: "below_minimum",
      minimum_aum_usd: "50000000",
      reason: "Reported AUM is below the $50,000,000 minimum",
    },
  };
  const unknown = {
    ...manager,
    slug: "unknown-manager",
    name: "Example Unverified Fund",
    aum_usd: null,
    aum_as_of: null,
    aum_source_url: null,
    aum_measurement: null,
    eligibility: {
      status: "unverified",
      minimum_aum_usd: "50000000",
      reason:
        "Official AUM amount, measurement, date and source must be verified",
    },
  };
  await page.route("**/api/research/managers", (route) =>
    route.fulfill({ json: { managers: [manager, below, unknown] } }),
  );
  await page.route("**/api/research/managers/unknown-manager", (route) =>
    route.fulfill({
      json: {
        ...unknown,
        filings: [
          {
            quarter: "2026-06-30",
            filed_date: "2026-08-14",
            source_url: "https://example.com/filing",
          },
        ],
      },
    }),
  );
  await page.route(
    "**/api/research/managers/unknown-manager/changes?*",
    (route) => route.fulfill({ json: comparison }),
  );
  await page.goto("/#research");
  await expect(page.getByRole("button", { name: manager.name })).toBeVisible();
  await expect(page.getByRole("button", { name: below.name })).toHaveCount(0);
  await expect(page.getByRole("button", { name: unknown.name })).toHaveCount(0);
  await expect(page.getByText("Minimum verified AUM: $50M.")).toBeVisible();
  await expect(page.getByText("$100M · 2026-01-01")).toBeVisible();
  await expect(page.locator('a[href="https://example.com/aum"]')).toHaveCount(
    0,
  );
  await page.getByLabel("Show unverified or below-minimum managers").check();
  await expect(page.getByRole("button", { name: below.name })).toBeVisible();
  await expect(page.getByRole("button", { name: unknown.name })).toBeVisible();
  await expect(page.getByText(/Reported AUM is below the/)).toBeVisible();
  await expect(page.getByText(/AUM unverified/)).toBeVisible();
  await page.getByRole("button", { name: unknown.name }).click();
  await expect(
    page.getByLabel("Manager research").getByText(/AUM unverified/),
  ).toBeVisible();
  await expect(
    page.getByRole("region", {
      name: "Quantity increased positions",
      exact: true,
    }),
  ).toContainText("Example New Cloud");
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});

test("compact values preserve share direction and expose exact amounts", async ({
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
        ],
      },
    }),
  );
  const values = [
    "8781829133",
    "999999",
    "1000000",
    "-1200000",
    "999",
    "1",
    "0",
  ];
  await page.route(
    "**/api/research/managers/example-manager/changes?*",
    (route) =>
      route.fulfill({
        json: {
          ...comparison,
          changes: values.map((value, index) => ({
            ...comparison.changes[4],
            cusip: String(index).padStart(9, "0"),
            issuer: `Example price effect ${index}`,
            value_change_usd: value,
            weight_change: "0.0896595669",
          })),
        },
      }),
  );
  await page.goto("/#research");
  await page.getByRole("button", { name: manager.name }).click();
  const decreased = page.getByRole("region", {
    name: "Quantity decreased positions",
    exact: true,
  });
  const expected = [
    "+$8,781M",
    "+$999K",
    "+$1M",
    "-$1M",
    "+$0.999K",
    "+$0.001K",
    "$0K",
  ];
  for (let index = 0; index < values.length; index++) {
    const row = decreased.locator("tbody tr").nth(index);
    await expect(row).toContainText(expected[index]);
    await expect(row).toContainText("90 → 80 SH");
    await expect(row).toContainText("+8.97 pp");
  }
  await expect(
    decreased.locator("tbody tr").first().locator("td").nth(1).locator("span"),
  ).toHaveAttribute("title", "+$8,781,829,133");
});

test("annual net change uses year selection and preserves quarterly comparison", async ({
  page,
}) => {
  await page.route("**/api/research/managers", (route) =>
    route.fulfill({ json: { managers: [manager] } }),
  );
  await page.route("**/api/research/managers/example-manager", (route) =>
    route.fulfill({
      json: {
        ...manager,
        filings: ["2026-06-30", "2026-03-31", "2025-12-31", "2024-12-31"].map(
          (quarter) => ({
            quarter,
            filed_date: "2026-08-14",
            source_url: "https://example.com/filing",
          }),
        ),
      },
    }),
  );
  await page.route(
    "**/api/research/managers/example-manager/changes?*",
    (route) => route.fulfill({ json: comparison }),
  );
  await page.route(
    "**/api/research/managers/example-manager/annual-changes?*",
    (route) => {
      const year = Number(
        new URL(route.request().url()).searchParams.get("year"),
      );
      return route.fulfill({
        json: {
          ...comparison,
          year,
          quarter: year === 2026 ? "2026-06-30" : `${year}-12-31`,
          previous_quarter: `${year - 1}-12-31`,
          year_to_date: year === 2026,
          status: year === 2025 ? "unavailable" : "available",
          reason:
            year === 2025
              ? "2025-03-31: No original or restated holdings available"
              : null,
          changes: year === 2025 ? [] : comparison.changes,
        },
      });
    },
  );
  await page.goto("/#research");
  await page.getByRole("button", { name: manager.name }).click();
  await expect(
    page.getByRole("region", {
      name: "Quarterly position changes",
      exact: true,
    }),
  ).toBeVisible();
  await page.getByLabel("Comparison view").selectOption("annual");
  await expect(page.getByLabel("Report year")).toHaveValue("2026");
  await expect(page.getByLabel("Report quarter")).toHaveCount(0);
  await expect(page.getByText("2025 Q4 → 2026 Q2 · YTD")).toBeVisible();
  await expect(
    page.getByRole("region", {
      name: "Annual net position changes",
      exact: true,
    }),
  ).toContainText("Example New Cloud");
  await page.getByLabel("Report year").selectOption("2025");
  await expect(
    page.getByText(
      "Comparison unavailable: 2025-03-31: No original or restated holdings available",
    ),
  ).toBeVisible();
  await expect(
    page.getByRole("region", {
      name: "Annual net position changes",
      exact: true,
    }),
  ).toHaveCount(0);
  await page.getByLabel("Report year").selectOption("2024");
  await expect(page.getByText("2023 Q4 → 2024 Q4")).toBeVisible();
  await page.getByLabel("Comparison view").selectOption("quarterly");
  await expect(page.getByLabel("Report quarter")).toHaveValue("2026-06-30");
  await expect(
    page.getByRole("region", {
      name: "Quarterly position changes",
      exact: true,
    }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});
