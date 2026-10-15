import { expect, test } from "@playwright/test";

const managers = Array.from({ length: 18 }, (_, index) => ({
  slug: `manager-${index}`,
  name: `Example Manager ${index + 1}`,
  investor_names: ["Example Investor"],
  cik: "0000000000",
  website_url: null,
  letters_url: null,
  focus: "Value investing",
  history_start_year: 2010,
  portfolio_company_count: 25,
  portfolio_company_count_quarter: "2026-06-30",
  history_source_url: null,
  source_urls: [],
  aum_usd: "100000000",
  aum_as_of: "2026-01-01",
  aum_source_url: "https://example.com/aum",
  aum_measurement: "firm_aum",
  eligibility: {
    status: "eligible",
    minimum_aum_usd: "50000000",
    reason: null,
  },
  coverage: {
    quarters: 2,
    first_quarter: "2026-03-31",
    last_quarter: "2026-06-30",
    continuous_decade: false,
  },
}));

test.beforeEach(async ({ page }) => {
  await page.route("**/api/research/managers", (route) =>
    route.fulfill({ json: { managers } }),
  );
  await page.route("**/api/research/managers/manager-*", (route) =>
    route.fulfill({
      json: {
        ...managers.find((manager) =>
          route.request().url().endsWith(`/${manager.slug}`),
        ),
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
  await page.route("**/api/research/managers/*/changes?*", (route) =>
    route.fulfill({
      json: {
        quarter: "2026-06-30",
        previous_quarter: "2026-03-31",
        status: "available",
        reason: null,
        source_urls: [],
        changes: Array.from({ length: 25 }, (_, index) => ({
          cusip: String(index).padStart(9, "0"),
          issuer: `Example Company ${index + 1}`,
          security_class: "COM",
          put_call: "",
          share_type: "SH",
          kind: "increased",
          category: "increased",
          previous_quantity: "100",
          current_quantity: "200",
          quantity_change: "100",
          current_value_usd: "20000",
          value_change_usd: "10000",
          current_weight: "0.04",
          weight_change: "0",
        })),
      },
    }),
  );
  await page.goto("/#research");
});

test("manager panels scroll independently and selection preserves the directory position", async ({
  page,
  isMobile,
}) => {
  test.skip(isMobile, "Desktop panels use independent scroll regions.");
  const directory = page.getByRole("region", { name: "Manager directory" });
  const detail = page.getByLabel("Manager research");
  await directory
    .getByRole("button", { name: "Example Manager 1", exact: true })
    .click();
  await expect(detail.getByRole("table")).toBeVisible();
  const bounds = await page.locator(".research-layout").boundingBox();
  expect(bounds!.y + bounds!.height).toBeLessThanOrEqual(
    await page.evaluate(() => innerHeight),
  );
  await directory.hover();
  await page.mouse.wheel(0, 550);
  await expect
    .poll(() => directory.evaluate((element) => element.scrollTop))
    .toBeGreaterThan(100);
  expect(await detail.evaluate((element) => element.scrollTop)).toBe(0);
  const directoryOffset = await directory.evaluate(
    (element) => element.scrollTop,
  );
  const pageOffset = await page.evaluate(() => scrollY);
  const detailBounds = await detail.boundingBox();
  await page.mouse.move(
    detailBounds!.x + detailBounds!.width / 2,
    Math.max(detailBounds!.y, 100) + 80,
  );
  await page.mouse.wheel(0, 600);
  await expect
    .poll(() => detail.evaluate((element) => element.scrollTop))
    .toBeGreaterThan(100);
  expect(await directory.evaluate((element) => element.scrollTop)).toBe(
    directoryOffset,
  );
  expect(await page.evaluate(() => scrollY)).toBe(pageOffset);
  const visibleName = await directory
    .locator("button.manager-link")
    .evaluateAll((buttons) => {
      const parent = buttons[0]
        .closest(".research-directory")!
        .getBoundingClientRect();
      return buttons.find((button) => {
        const bounds = button.getBoundingClientRect();
        return (
          bounds.top >= Math.max(parent.top, 100) &&
          bounds.bottom <= parent.bottom
        );
      })!.textContent!;
    });
  await directory
    .getByRole("button", { name: visibleName, exact: true })
    .click();
  await expect(
    detail.getByRole("heading", { name: visibleName, exact: true }),
  ).toBeVisible();
  await expect(detail).toBeFocused();
  expect(await directory.evaluate((element) => element.scrollTop)).toBe(
    directoryOffset,
  );
  expect(await detail.evaluate((element) => element.scrollTop)).toBe(0);
  expect(await page.evaluate(() => scrollY)).toBe(pageOffset);
  await directory.hover();
  await page.mouse.wheel(0, 10000);
  await expect(
    directory.getByRole("button", { name: "Example Manager 18", exact: true }),
  ).toBeInViewport({ ratio: 1 });
  await detail.hover();
  await page.mouse.wheel(0, 10000);
  await expect(
    detail.getByText("Source notes", { exact: true }),
  ).toBeInViewport({ ratio: 1 });
});

test("mobile selection reaches detail without trapping the manager list", async ({
  page,
  isMobile,
}) => {
  test.skip(!isMobile, "Mobile keeps the single-column document flow.");
  const directory = page.getByRole("region", { name: "Manager directory" });
  const detail = page.getByLabel("Manager research");
  await directory
    .getByRole("button", { name: "Example Manager 18", exact: true })
    .click();
  await expect(
    detail.getByRole("heading", { name: "Example Manager 18", exact: true }),
  ).toBeVisible();
  await expect(detail).toBeFocused();
  expect(
    await directory.evaluate(
      (element) => element.scrollHeight === element.clientHeight,
    ),
  ).toBe(true);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await directory
    .getByRole("button", { name: "Example Manager 1", exact: true })
    .click();
  await expect(
    detail.getByRole("heading", { name: "Example Manager 1", exact: true }),
  ).toBeVisible();
});
