import { expect, test } from "@playwright/test";

test("connects to the real API and fits the viewport", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(
    "Your investment workspace.",
  );
  await expect(page.getByRole("status")).toHaveText("Connected");
  await page.getByRole("button", { name: "Check connection" }).click();
  await expect(page.getByRole("status")).toHaveText("Connected");
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  expect(errors).toEqual([]);
});

test("shows disconnect and recovers against the real API", async ({ page }) => {
  await page.route("**/api/health", (route) => route.abort());
  await page.goto("/");
  await expect(page.getByRole("status")).toHaveText("Disconnected");
  await page.unroute("**/api/health");
  await page.getByRole("button", { name: "Check connection" }).click();
  await expect(page.getByRole("status")).toHaveText("Connected");
});

test("does not treat a wrong service or error as healthy", async ({ page }) => {
  await page.route("**/api/health", (route) =>
    route.fulfill({
      json: { status: "ok", service: "unrelated-service" },
    }),
  );
  await page.goto("/");
  await expect(page.getByRole("status")).toHaveText("Disconnected");
  await page.route("**/api/health", (route) =>
    route.fulfill({ status: 503, body: "Unavailable" }),
  );
  await page.getByRole("button", { name: "Check connection" }).click();
  await expect(page.getByRole("status")).toHaveText("Disconnected");
});

test("times out an unresponsive service", async ({ page }) => {
  await page.route("**/api/health", () => {});
  await page.goto("/");
  await expect(page.getByRole("status")).toHaveText("Disconnected", {
    timeout: 6000,
  });
});
