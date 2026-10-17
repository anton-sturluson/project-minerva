import { expect, test } from "@playwright/test";

function contributor(
  name: string,
  slug: string,
  delta: string,
  previous = "0.04",
  current = "0.05",
) {
  return {
    slug,
    name,
    kind: "increased",
    previous_quantity: "100",
    current_quantity: "120",
    previous_weight: previous,
    current_weight: current,
    weight_change_pp: delta,
    quarter_end_price_usd: "123.45",
    price_as_of: "2026-06-30",
    source_urls: [
      `https://example.com/${slug}/previous`,
      `https://example.com/${slug}/current`,
    ],
  };
}
const activity = {
  quarter: "2026-06-30",
  previous_quarter: "2026-03-31",
  available_quarters: ["2026-06-30", "2026-03-31"],
  status: "available",
  reason: null,
  included_managers: 3,
  total_managers: 5,
  excluded_managers: [
    {
      slug: "missing",
      name: "Example Missing Manager",
      reason: "Previous quarter is missing",
    },
    {
      slug: "empty",
      name: "Example Empty Manager",
      reason: "Current reported value is zero",
    },
  ],
  increased: [
    {
      cusip: "123456780",
      issuer: "Example Cloud",
      security_class: "COM",
      manager_count: 2,
      average_weight_change_pp: "0.5",
      contributors: [
        contributor("Example Alpha", "alpha", "1"),
        contributor("Example Beta", "beta", "0", "0.08", "0.08"),
      ],
    },
    {
      cusip: "123456781",
      issuer: "Example Software",
      security_class: "COM",
      manager_count: 1,
      average_weight_change_pp: "2",
      contributors: [
        {
          ...contributor("Example Gamma", "gamma", "2", "0", "0.02"),
          kind: "new",
          previous_quantity: "0",
        },
      ],
    },
    {
      cusip: "123456782",
      issuer: "Example Tools",
      security_class: "COM",
      manager_count: 1,
      average_weight_change_pp: "1",
      contributors: [contributor("Example Alpha", "alpha", "1")],
    },
  ],
  decreased: [
    {
      cusip: "123456783",
      issuer: "Example Semiconductors",
      security_class: "COM",
      manager_count: 2,
      average_weight_change_pp: "-3",
      contributors: [
        {
          ...contributor("Example Alpha", "alpha", "-3", "0.05", "0.02"),
          kind: "decreased",
          current_quantity: "80",
        },
        {
          ...contributor("Example Beta", "beta", "-3", "0.05", "0.02"),
          kind: "decreased",
          current_quantity: "80",
        },
      ],
    },
    {
      cusip: "123456784",
      issuer: "Example Exit",
      security_class: "COM",
      manager_count: 1,
      average_weight_change_pp: "-5",
      contributors: [
        {
          ...contributor("Example Gamma", "gamma", "-5", "0.05", "0"),
          kind: "exited",
          current_quantity: "0",
        },
      ],
    },
    {
      cusip: "123456785",
      issuer: "Example Devices",
      security_class: "COM",
      manager_count: 1,
      average_weight_change_pp: "-1",
      contributors: [
        {
          ...contributor("Example Alpha", "alpha", "-1", "0.05", "0.04"),
          kind: "decreased",
          current_quantity: "80",
        },
      ],
    },
  ],
};

test("stock activity ranks by manager count and opens compact sourced manager tables", async ({
  page,
}) => {
  await page.route("**/api/accounts", (route) => route.fulfill({ json: [] }));
  await page.route("**/api/research/activity", (route) =>
    route.fulfill({ json: activity }),
  );
  await page.route("**/api/research/managers", (route) =>
    route.fulfill({ json: { managers: [] } }),
  );
  await page.goto("/#research/activity");
  await expect(page.getByText("3 of 5 managers included.")).toBeVisible();
  await expect(page.getByLabel("Report quarter")).toHaveValue("2026-06-30");
  const increased = page.getByRole("region", {
    name: "Most increased",
    exact: true,
  });
  const decreased = page.getByRole("region", {
    name: "Most decreased",
    exact: true,
  });
  const stocks = increased.locator(".activity-stock-row");
  await expect(stocks).toHaveCount(3);
  await expect(stocks.locator("button")).toHaveText([
    "▸ Example Cloud",
    "▸ Example Software",
    "▸ Example Tools",
  ]);
  await expect(stocks.first().getByRole("cell").nth(1)).toHaveText("2");
  await expect(stocks.first().getByRole("cell").nth(2)).toHaveText("6.50%");
  await expect(stocks.first().getByRole("cell").nth(3)).toHaveText("+0.50 pp");
  await expect(decreased.locator(".activity-stock-row button")).toHaveText([
    "▸ Example Semiconductors",
    "▸ Example Exit",
    "▸ Example Devices",
  ]);
  await expect(increased.getByRole("table")).toHaveCount(1);
  await expect(page.getByText(/Default order:/)).toHaveCount(0);
  await expect(
    page.getByText("How activity is measured", { exact: true }),
  ).toHaveCount(0);
  const toggle = increased.getByRole("button", {
    name: "Example Cloud",
    exact: true,
  });
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  await toggle.focus();
  await page.keyboard.press("Enter");
  await expect(toggle).toHaveAttribute("aria-expanded", "true");
  const managers = increased.getByRole("table", {
    name: "Example Cloud managers",
    exact: true,
  });
  const rows = managers.locator("tbody tr");
  await expect(rows).toHaveCount(2);
  await expect(rows.first()).toContainText("Example Beta");
  await expect(rows.first()).toContainText("8.00% → 8.00%");
  await expect(rows.nth(1)).toContainText("Example Alpha");
  await expect(rows.nth(1)).toContainText("100 → 120");
  await expect(rows.nth(1)).toContainText("4.00% → 5.00%");
  await expect(rows.nth(1)).toContainText("+1.00 pp");
  await expect(rows.nth(1)).toContainText("$123.45");
  await expect(rows.nth(1)).toContainText("2026-06-30");
  for (const [index, slug] of ["beta", "alpha"].entries()) {
    await expect(
      rows.nth(index).getByRole("link", { name: "Filing source 1" }),
    ).toHaveAttribute("href", `https://example.com/${slug}/previous`);
    await expect(
      rows.nth(index).getByRole("link", { name: "Filing source 2" }),
    ).toHaveAttribute("href", `https://example.com/${slug}/current`);
  }
  await expect(managers.locator("xpath=../..")).toHaveAttribute("colspan", "4");
  await page.getByText("Excluded managers (2)", { exact: true }).click();
  await expect(page.getByText("Previous quarter is missing")).toBeVisible();
  await expect(page.getByText("Current reported value is zero")).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.getByRole("link", { name: "[ Managers ]", exact: true }).click();
  await expect(page).toHaveURL(/#research$/);
  await page.goBack();
  await expect(page).toHaveURL(/#research\/activity$/);
  await expect(
    page.getByRole("heading", { name: "Stock activity", exact: true }),
  ).toBeVisible();
});

test("quarter errors preserve selection and retry recovers empty activity", async ({
  page,
}) => {
  let failPrevious = true;
  await page.route("**/api/research/activity*", (route) => {
    if (!route.request().url().includes("quarter=2026-03-31"))
      return route.fulfill({ json: activity });
    return failPrevious
      ? route.fulfill({
          status: 503,
          json: { detail: "Example quarter unavailable" },
        })
      : route.fulfill({
          json: {
            ...activity,
            quarter: "2026-03-31",
            previous_quarter: "2025-12-31",
            increased: [],
            decreased: [],
          },
        });
  });
  await page.goto("/#research/activity");
  await page.getByLabel("Report quarter").selectOption("2026-03-31");
  await expect(page.getByRole("alert")).toContainText(
    "Example quarter unavailable",
  );
  await expect(page.getByLabel("Report quarter")).toHaveValue("2026-03-31");
  await expect(
    page.getByRole("region", { name: "Most increased", exact: true }),
  ).toHaveCount(0);
  failPrevious = false;
  await page.getByRole("button", { name: "Try again" }).click();
  await expect(page.getByText("2026 Q1 compared with 2025 Q4")).toBeVisible();
  await expect(page.getByLabel("Report quarter")).toHaveValue("2026-03-31");
  await expect(
    page.getByText("No reported quantity changes in this direction."),
  ).toHaveCount(2);
});

test("initial failure recovers and unavailable coverage is explicit", async ({
  page,
}) => {
  let failure = true;
  await page.route("**/api/research/activity*", (route) =>
    failure
      ? route.fulfill({
          status: 503,
          json: { detail: "Example activity unavailable" },
        })
      : route.fulfill({
          json: {
            ...activity,
            quarter: null,
            previous_quarter: null,
            available_quarters: [],
            included_managers: 0,
            status: "unavailable",
            reason: "No adjacent quarters loaded",
            increased: [],
            decreased: [],
          },
        }),
  );
  await page.goto("/#research/activity");
  await expect(page.getByRole("alert")).toContainText(
    "Example activity unavailable",
  );
  failure = false;
  await page.getByRole("button", { name: "Try again" }).click();
  await expect(
    page.getByText("Stock activity unavailable: No adjacent quarters loaded"),
  ).toBeVisible();
  await expect(page.getByText("0 of 5 managers included.")).toBeVisible();
  await expect(page.getByLabel("Report quarter")).toHaveCount(0);
  await expect(
    page.getByRole("region", { name: "Most increased", exact: true }),
  ).toHaveCount(0);
});

test("stock and manager pages show ten at a time and reset after folding or quarter changes", async ({
  page,
}) => {
  const contributors = Array.from({ length: 23 }, (_, index) =>
    contributor(
      `Example Manager ${String(index + 1).padStart(2, "0")}`,
      `manager-${index}`,
      "1",
      "0",
      String((23 - index) / 100),
    ),
  );
  const increased = Array.from({ length: 23 }, (_, index) => ({
    ...activity.increased[0],
    cusip: String(123456800 + index),
    issuer: `Example Stock ${String(index + 1).padStart(2, "0")}`,
    manager_count: index === 0 ? 23 : 1,
    contributors: index === 0 ? contributors : [contributors[0]],
  }));
  await page.route("**/api/accounts", (route) => route.fulfill({ json: [] }));
  await page.route("**/api/research/activity*", (route) =>
    route.fulfill({
      json: {
        ...activity,
        increased,
        decreased: [],
        quarter: route.request().url().includes("quarter=2026-03-31")
          ? "2026-03-31"
          : activity.quarter,
      },
    }),
  );
  await page.goto("/#research/activity");
  const list = page.getByRole("region", {
    name: "Most increased",
    exact: true,
  });
  const stocks = list.locator(".activity-stock-row");
  const pages = list.getByLabel("Most increased stock pages");
  await expect(stocks).toHaveCount(10);
  await expect(list.getByRole("table")).toHaveCount(1);
  await pages.getByRole("button", { name: "Show 10 more" }).click();
  await expect(stocks).toHaveCount(20);
  await pages.getByRole("button", { name: "Show 10 more" }).click();
  await expect(stocks).toHaveCount(23);
  await expect(pages.getByRole("button", { name: "Show 10 more" })).toHaveCount(
    0,
  );
  await pages.getByRole("button", { name: "Show fewer" }).click();
  await expect(stocks).toHaveCount(10);
  const toggle = list.getByRole("button", {
    name: "Example Stock 01",
    exact: true,
  });
  await toggle.click();
  const managers = list.getByRole("table", {
    name: "Example Stock 01 managers",
    exact: true,
  });
  const managerPages = list.getByLabel("Example Stock 01 manager pages");
  await expect(managers.locator("tbody tr")).toHaveCount(10);
  await managerPages.getByRole("button", { name: "Show 10 more" }).click();
  await expect(managers.locator("tbody tr")).toHaveCount(20);
  await managerPages.getByRole("button", { name: "Show 10 more" }).click();
  await expect(managers.locator("tbody tr")).toHaveCount(23);
  await expect(
    managerPages.getByRole("button", { name: "Show 10 more" }),
  ).toHaveCount(0);
  await expect(
    managers
      .locator("tbody tr")
      .last()
      .getByRole("link", { name: "Filing source 2" }),
  ).toHaveAttribute("href", "https://example.com/manager-22/current");
  await managerPages.getByRole("button", { name: "Show fewer" }).click();
  await expect(managers.locator("tbody tr")).toHaveCount(10);
  await managerPages.getByRole("button", { name: "Show 10 more" }).click();
  await toggle.click();
  await expect(managers).toHaveCount(0);
  await toggle.click();
  await expect(managers.locator("tbody tr")).toHaveCount(10);
  await pages.getByRole("button", { name: "Show 10 more" }).click();
  await list.getByRole("button", { name: "Security", exact: true }).click();
  await expect(stocks).toHaveCount(10);
  await pages.getByRole("button", { name: "Show 10 more" }).click();
  await page.getByLabel("Report quarter").selectOption("2026-03-31");
  await expect(stocks).toHaveCount(10);
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  await expect(
    list.getByRole("columnheader", { name: "Managers", exact: true }),
  ).toHaveAttribute("aria-sort", "descending");
});

test("every activity column sorts the full list before pagination", async ({
  page,
}) => {
  const increased = Array.from({ length: 23 }, (_, index) => ({
    cusip: String(123456800 + index),
    issuer: `Example Stock ${String(index + 1).padStart(2, "0")}`,
    security_class: "COM",
    manager_count: index === 22 ? 12 : index === 0 ? 10 : index === 1 ? 2 : 1,
    average_weight_change_pp: ["-10", "-2", "2", "10"][index % 4],
    contributors: Array.from(
      { length: index === 22 ? 12 : index === 0 ? 10 : index === 1 ? 2 : 1 },
      (_, manager) =>
        contributor(
          `Example Manager ${manager + 1}`,
          `example-${index}-${manager}`,
          "1",
          "0.1",
          String(index === 22 ? 0.01 : (20 + index) / 100),
        ),
    ),
  }));
  await page.route("**/api/accounts", (route) => route.fulfill({ json: [] }));
  await page.route("**/api/research/activity*", (route) =>
    route.fulfill({ json: { ...activity, increased, decreased: [] } }),
  );
  await page.goto("/#research/activity");
  const list = page.getByRole("region", {
    name: "Most increased",
    exact: true,
  });
  const stocks = list.locator(".activity-stock-row");
  const first = stocks.first();
  await expect(stocks).toHaveCount(10);
  await expect(first).toContainText("Example Stock 23");
  await expect(
    list.getByRole("columnheader", { name: "Managers", exact: true }),
  ).toHaveAttribute("aria-sort", "descending");
  await list.getByRole("button", { name: "Managers", exact: true }).click();
  await expect(first).toContainText("Example Stock 03");
  await list.getByRole("button", { name: "Security", exact: true }).click();
  await expect(first).toContainText("Example Stock 01");
  await list.getByRole("button", { name: "Security", exact: true }).click();
  await expect(first).toContainText("Example Stock 23");
  await list
    .getByRole("button", { name: "Average 13F weight", exact: true })
    .click();
  await expect(first).toContainText("Example Stock 22");
  await expect(first.getByRole("cell").nth(2)).toHaveText("41.00%");
  await list
    .getByRole("button", { name: "Average 13F weight", exact: true })
    .click();
  await expect(first).toContainText("Example Stock 23");
  await list
    .getByRole("button", { name: "Average weight change", exact: true })
    .click();
  await expect(first).toContainText("Example Stock 04");
  await expect(first.getByRole("cell").nth(3)).toHaveText("+10.00 pp");
  await list
    .getByRole("button", { name: "Average weight change", exact: true })
    .click();
  await expect(first).toContainText("Example Stock 01");
  await expect(first.getByRole("cell").nth(3)).toHaveText("-10.00 pp");
});

test("manager tables preserve weight order, tie sources, exit price dates and unavailable prices on narrow screens", async ({
  page,
}) => {
  const contributors = [
    {
      ...contributor("Example Exit", "exit", "-5", "0.05", "0"),
      kind: "exited",
      current_quantity: "0",
      quarter_end_price_usd: "98.765",
      price_as_of: "2026-03-31",
    },
    {
      ...contributor("Example Equal", "equal-b", "-5", "0.1", "0.05"),
      kind: "decreased",
    },
    {
      ...contributor("Example Equal", "equal-a", "-5", "0.1", "0.05"),
      kind: "decreased",
    },
    {
      ...contributor("Example Alpha", "alpha", "-5", "0.1", "0.05"),
      kind: "decreased",
      quarter_end_price_usd: null,
      price_as_of: null,
      previous_quantity: "100.125",
      current_quantity: "80.0625",
    },
    {
      ...contributor(
        "Example Largest Fund With A Long Name",
        "largest",
        "-10",
        "0.2",
        "0.1",
      ),
      kind: "decreased",
    },
  ];
  await page.route("**/api/accounts", (route) => route.fulfill({ json: [] }));
  await page.route("**/api/research/activity*", (route) =>
    route.fulfill({
      json: {
        ...activity,
        increased: [],
        decreased: [
          {
            ...activity.decreased[0],
            issuer: "Example Sorted Reduction",
            manager_count: 5,
            contributors,
          },
        ],
      },
    }),
  );
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/#research/activity");
  const list = page.getByRole("region", {
    name: "Most decreased",
    exact: true,
  });
  await list
    .getByRole("button", { name: "Example Sorted Reduction", exact: true })
    .click();
  const table = list.getByRole("table", {
    name: "Example Sorted Reduction managers",
    exact: true,
  });
  const managers = table.locator("tbody tr");
  await expect(managers).toHaveCount(5);
  await expect(managers.getByRole("rowheader")).toHaveText([
    "Example Largest Fund With A Long NameDecreased",
    "Example AlphaDecreased",
    "Example EqualDecreased",
    "Example EqualDecreased",
    "Example ExitExited",
  ]);
  await expect(
    managers.nth(2).getByRole("link", { name: "Filing source 2" }),
  ).toHaveAttribute("href", "https://example.com/equal-a/current");
  await expect(
    managers.nth(3).getByRole("link", { name: "Filing source 2" }),
  ).toHaveAttribute("href", "https://example.com/equal-b/current");
  await expect(managers.nth(1)).toContainText("Unavailable");
  await expect(managers.nth(1)).toContainText("100.125 → 80.0625");
  await expect(managers.last()).toContainText("$98.77");
  await expect(managers.last()).toContainText("2026-03-31");
  await expect(
    table.getByRole("columnheader", { name: "Quarter-end price" }),
  ).toHaveAttribute("title", /not a purchase price/);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});
