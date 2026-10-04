import { expect, test } from "./fixtures";

test("separates pages, folds activity and preserves an entry draft on back navigation", async ({
  page,
}) => {
  await page.goto("/#activity");
  await expect(
    page.getByRole("heading", { name: "Activity", exact: true }),
  ).toBeVisible();
  await expect(page.getByLabel("Cash amount", { exact: true })).toBeHidden();
  await expect(
    page.getByLabel("Account activity", { exact: true }),
  ).toBeHidden();
  await page.getByText("Record cash", { exact: true }).click();
  await page.getByLabel("Cash amount", { exact: true }).fill("12.34");
  await page.getByRole("link", { name: "Back to top ↑", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Activity", exact: true }),
  ).toBeVisible();
  await page.getByRole("link", { name: "[ Research ]", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Research", exact: true }),
  ).toBeVisible();
  await expect(page.getByLabel("Cash amount", { exact: true })).toBeHidden();
  await expect(page.getByTestId("payoff-ratio")).toBeHidden();
  await page.goBack();
  await expect(page.getByLabel("Cash amount", { exact: true })).toBeVisible();
  await expect(page.getByLabel("Cash amount", { exact: true })).toHaveValue(
    "12.34",
  );
  await page.getByRole("link", { name: "[ Portfolio ]", exact: true }).click();
  await expect(page.getByTestId("payoff-ratio")).toBeVisible();
  await expect(page.getByText("Coming soon", { exact: true })).toBeHidden();
  await page.locator(".page-footer").scrollIntoViewIfNeeded();
  const header = await page.getByRole("banner").boundingBox();
  expect(header!.y).toBe(0);
  await page
    .getByRole("link", { name: "[ Performance ]", exact: true })
    .click();
  const heading = await page
    .getByRole("heading", { name: "Stocks vs. the market" })
    .boundingBox();
  expect(heading!.y).toBeGreaterThanOrEqual(header!.height);
  await page.getByRole("link", { name: "[ Research ]", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Research", exact: true }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});
