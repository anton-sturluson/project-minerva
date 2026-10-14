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

test("stock activity ranks, contributor sources, coverage and hash navigation", async ({
  page,
}) => {
  await page.route("**/api/research/activity", (route) =>
    route.fulfill({ json: activity }),
  );
  await page.route("**/api/research/managers", (route) =>
    route.fulfill({ json: { managers: [] } }),
  );
  await page.goto("/#research/activity");
  await expect(
    page.getByRole("heading", { name: "Research", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: "[ Stock activity ]", exact: true }),
  ).toHaveAttribute("aria-current", "page");
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
  await expect(increased.locator("tbody tr")).toHaveCount(3);
  await expect(increased.locator("tbody tr").nth(0)).toContainText(
    "Example Cloud",
  );
  await expect(
    increased.locator("tbody tr").nth(0).getByRole("cell").nth(1),
  ).toHaveText("2");
  await expect(
    increased.locator("tbody tr").nth(0).getByRole("cell").nth(2),
  ).toHaveText("6.50%");
  await expect(
    increased.locator("tbody tr").nth(0).getByRole("cell").nth(3),
  ).toHaveText("+0.50 pp");
  await expect(increased.locator("tbody tr").nth(1)).toContainText(
    "Example Tools",
  );
  await expect(increased.locator("tbody tr").nth(2)).toContainText(
    "Example Software",
  );
  await expect(decreased.locator("tbody tr").nth(0)).toContainText(
    "Example Devices",
  );
  await expect(decreased.locator("tbody tr").nth(1)).toContainText(
    "Example Semiconductors",
  );
  await expect(decreased.locator("tbody tr").nth(2)).toContainText(
    "Example Exit",
  );
  await increased.locator("summary").first().click();
  const beta = increased.locator(".activity-contributors li").first();
  await expect(beta).toContainText("Example Beta");
  await expect(beta).toContainText("8.00% → 8.00%");
  await expect(
    beta.getByRole("link", { name: "Filing source 2" }),
  ).toHaveAttribute("href", "https://example.com/beta/current");
  const alpha = increased.locator(".activity-contributors li").nth(1);
  await expect(alpha).toContainText("Example Alpha");
  await expect(alpha).toContainText("4.00% → 5.00% · +1.00 pp");
  await expect(alpha).toContainText("Reported shares: 100 → 120");
  await expect(
    alpha.getByRole("link", { name: "Filing source 2" }),
  ).toHaveAttribute("href", "https://example.com/alpha/current");
  await expect(
    increased.locator(".activity-contributors li").first(),
  ).toContainText("Example Beta");
  await decreased.locator("summary").nth(2).click();
  await expect(
    decreased.locator(".activity-contributors").nth(2),
  ).toContainText("Exited · 5.00% → 0.00% · -5.00 pp");
  await page.getByText("Excluded managers (2)", { exact: true }).click();
  await expect(page.getByText("Previous quarter is missing")).toBeVisible();
  await expect(page.getByText("Current reported value is zero")).toBeVisible();
  await page.getByText("How activity is measured", { exact: true }).click();
  await expect(
    page.getByText(/Price changes alone do not count/),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.getByRole("link", { name: "[ Managers ]", exact: true }).click();
  await expect(page).toHaveURL(/#research$/);
  await expect(
    page.getByRole("heading", { name: "Managers", exact: true }),
  ).toBeVisible();
  await page.goBack();
  await expect(page).toHaveURL(/#research\/activity$/);
  await expect(
    page.getByRole("heading", { name: "Stock activity", exact: true }),
  ).toBeVisible();
  await page.goForward();
  await expect(
    page.getByRole("heading", { name: "Managers", exact: true }),
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

test("large activity lists show leaders and reset after changing quarter", async ({
  page,
}) => {
  const increased = [
    ...activity.increased,
    ...Array.from({ length: 19 }, (_, index) => ({
      ...activity.increased[2],
      cusip: String(123456800 + index),
      issuer: `Example Extra Stock ${index + 1}`,
    })),
  ];
  await page.route("**/api/research/activity*", (route) =>
    route.fulfill({
      json: {
        ...activity,
        quarter: route.request().url().includes("quarter=2026-03-31")
          ? "2026-03-31"
          : "2026-06-30",
        increased,
      },
    }),
  );
  await page.goto("/#research/activity");
  const leaders = page.getByRole("region", {
    name: "Most increased",
    exact: true,
  });
  await expect(
    leaders.getByText("Top 20 of 22", { exact: true }),
  ).toBeVisible();
  await expect(leaders.locator("tbody tr")).toHaveCount(20);
  await expect(
    leaders.locator("summary").filter({ hasText: "Example Extra Stock 19" }),
  ).toHaveCount(0);
  await leaders.getByRole("button", { name: "Show all", exact: true }).click();
  await expect(leaders.locator("tbody tr")).toHaveCount(22);
  await expect(
    leaders.locator("summary").filter({ hasText: "Example Extra Stock 19" }),
  ).toContainText("Example Extra Stock 19");
  await leaders
    .locator("summary")
    .filter({ hasText: "Example Extra Stock 19" })
    .click();
  await expect(
    leaders
      .locator("tbody tr")
      .filter({ hasText: "Example Extra Stock 19" })
      .getByRole("link", { name: "Filing source 2" }),
  ).toHaveAttribute("href", "https://example.com/alpha/current");
  await leaders
    .getByRole("button", { name: "Show top 20", exact: true })
    .click();
  await expect(leaders.locator("tbody tr")).toHaveCount(20);
  await leaders.getByRole("button", { name: "Show all", exact: true }).click();
  await page.getByLabel("Report quarter").selectOption("2026-03-31");
  await expect(leaders.locator("tbody tr")).toHaveCount(20);
  await expect(
    leaders.getByRole("button", { name: "Show all", exact: true }),
  ).toBeVisible();
  await expect(
    page
      .getByRole("region", { name: "Most decreased", exact: true })
      .getByText("3 stocks", { exact: true }),
  ).toBeVisible();
});

test("all activity columns sort the full list and preserve security sources", async ({
  page,
}) => {
  const increased = Array.from({ length: 22 }, (_, index) => {
    const count = index === 0 ? 10 : index === 1 ? 2 : 1;
    const currentWeight = String((20 + index) / 100);
    return {
      cusip: String(123456800 + index),
      issuer: `Example Stock ${String(index + 1).padStart(2, "0")}`,
      security_class: "COM",
      manager_count: count,
      average_weight_change_pp: ["-10", "-2", "2", "10"][index % 4],
      contributors: Array.from({ length: count }, (_, manager) =>
        contributor(
          `Example Manager ${manager + 1}`,
          `example-${index}-${manager}`,
          ["-10", "-2", "2", "10"][index % 4],
          String(
            Number(currentWeight) -
              Number(["-10", "-2", "2", "10"][index % 4]) / 100,
          ),
          currentWeight,
        ),
      ),
    };
  });
  await page.route("**/api/research/activity*", (route) =>
    route.fulfill({
      json: {
        ...activity,
        included_managers: 32,
        total_managers: 32,
        excluded_managers: [],
        quarter: route.request().url().includes("quarter=2026-03-31")
          ? "2026-03-31"
          : activity.quarter,
        previous_quarter: route.request().url().includes("quarter=2026-03-31")
          ? "2025-12-31"
          : activity.previous_quarter,
        increased,
        decreased: [],
      },
    }),
  );
  await page.goto("/#research/activity");
  const list = page.getByRole("region", {
    name: "Most increased",
    exact: true,
  });
  const rows = list.locator("tbody tr");
  const first = rows.first();
  await expect(rows).toHaveCount(20);
  await expect(first).toContainText("Example Stock 22");
  await expect(first.getByRole("cell").nth(2)).toHaveText("41.00%");
  await expect(
    list.getByRole("columnheader", { name: "Average 13F weight" }),
  ).toHaveAttribute("aria-sort", "descending");
  await first.locator("summary").click();
  await list.getByRole("button", { name: "Show all", exact: true }).click();
  await expect(rows).toHaveCount(22);
  await list.getByRole("button", { name: "Security", exact: true }).click();
  await expect(first).toContainText("Example Stock 01");
  await expect(
    list.getByRole("columnheader", { name: "Security" }),
  ).toHaveAttribute("aria-sort", "ascending");
  const retained = rows.filter({ hasText: "Example Stock 22" });
  await expect(
    retained.getByRole("link", { name: "Filing source 2" }),
  ).toBeVisible();
  await expect(
    retained.getByRole("link", { name: "Filing source 2" }),
  ).toHaveAttribute("href", "https://example.com/example-21-0/current");
  await list.getByRole("button", { name: "Security", exact: true }).click();
  await expect(first).toContainText("Example Stock 22");
  await list.getByRole("button", { name: "Managers", exact: true }).click();
  await expect(first).toContainText("Example Stock 01");
  await expect(first.getByRole("cell").nth(1)).toHaveText("10");
  await expect(rows.nth(1).getByRole("cell").nth(1)).toHaveText("2");
  await list.getByRole("button", { name: "Managers", exact: true }).click();
  await expect(first).toContainText("Example Stock 03");
  await list
    .getByRole("button", { name: "Average 13F weight", exact: true })
    .click();
  await expect(first).toContainText("Example Stock 22");
  await list
    .getByRole("button", { name: "Average 13F weight", exact: true })
    .click();
  await expect(first).toContainText("Example Stock 01");
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
  await list.getByRole("button", { name: "Show top 20", exact: true }).click();
  await expect(rows).toHaveCount(20);
  await expect(first).toContainText("Example Stock 01");
  await page.getByLabel("Report quarter").selectOption("2026-03-31");
  await expect(page.getByText("2026 Q1 compared with 2025 Q4")).toBeVisible();
  await expect(first).toContainText("Example Stock 22");
  await expect(
    list.getByRole("columnheader", { name: "Average 13F weight" }),
  ).toHaveAttribute("aria-sort", "descending");
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});

test("expanded reductions show largest current weights first with stable ties and exits last", async ({
  page,
}) => {
  const contributors = [
    {
      ...contributor("Example Exit", "exit", "-5", "0.05", "0"),
      kind: "exited",
      current_quantity: "0",
    },
    {
      ...contributor("Example Equal", "equal-b", "-5", "0.10", "0.05"),
      kind: "decreased",
      current_quantity: "80",
    },
    {
      ...contributor("Example Equal", "equal-a", "-5", "0.10", "0.05"),
      kind: "decreased",
      current_quantity: "80",
    },
    {
      ...contributor("Example Alpha", "alpha", "-5", "0.10", "0.05"),
      kind: "decreased",
      current_quantity: "80",
    },
    {
      ...contributor("Example Largest", "largest", "-10", "0.20", "0.10"),
      kind: "decreased",
      current_quantity: "80",
    },
  ];
  await page.route("**/api/research/activity*", (route) =>
    route.fulfill({
      json: {
        ...activity,
        included_managers: 5,
        total_managers: 5,
        excluded_managers: [],
        increased: [],
        decreased: [
          {
            cusip: "123456780",
            issuer: "Example Sorted Reduction",
            security_class: "COM",
            manager_count: 5,
            average_weight_change_pp: "-6",
            contributors,
          },
        ],
      },
    }),
  );
  await page.goto("/#research/activity");
  const list = page.getByRole("region", {
    name: "Most decreased",
    exact: true,
  });
  await expect(list.getByRole("cell").nth(2)).toHaveText("5.00%");
  await list.locator("summary").click();
  const managers = list.locator(".activity-contributors li");
  await expect(managers).toHaveCount(5);
  await expect(managers.locator("strong")).toHaveText([
    "Example Largest",
    "Example Alpha",
    "Example Equal",
    "Example Equal",
    "Example Exit",
  ]);
  await expect(managers.first()).toContainText("20.00% → 10.00%");
  await expect(
    managers.nth(2).getByRole("link", { name: "Filing source 2" }),
  ).toHaveAttribute("href", "https://example.com/equal-a/current");
  await expect(
    managers.nth(3).getByRole("link", { name: "Filing source 2" }),
  ).toHaveAttribute("href", "https://example.com/equal-b/current");
  await expect(managers.last()).toContainText(
    "Exited · 5.00% → 0.00% · -5.00 pp",
  );
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});
