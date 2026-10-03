import { expect, test } from "./fixtures";

test("theme follows the system, supports overrides, and survives reload", async ({
  page,
}) => {
  await page.emulateMedia({ colorScheme: "dark" });
  await page.goto("/");
  const picker = page.getByLabel("Theme", { exact: true });
  await expect(picker).toHaveValue("system");
  await expect(page.locator("html")).toHaveCSS(
    "background-color",
    "rgb(34, 36, 33)",
  );
  await picker.selectOption("light");
  await expect(page.locator("html")).toHaveCSS(
    "background-color",
    "rgb(255, 254, 249)",
  );
  await page.reload();
  await expect(picker).toHaveValue("light");
  await picker.selectOption("dark");
  await page.emulateMedia({ colorScheme: "light" });
  await expect(page.locator("html")).toHaveCSS(
    "background-color",
    "rgb(34, 36, 33)",
  );
  await picker.selectOption("system");
  await expect(page.locator("html")).toHaveCSS(
    "background-color",
    "rgb(255, 254, 249)",
  );
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});

test("theme switch remains usable when storage is blocked", async ({
  page,
}) => {
  await page.addInitScript(() => {
    Storage.prototype.getItem = () => {
      throw new Error("Storage disabled");
    };
    Storage.prototype.setItem = () => {
      throw new Error("Storage disabled");
    };
  });
  await page.goto("/");
  await page.getByLabel("Theme", { exact: true }).selectOption("dark");
  await expect(page.locator("html")).toHaveCSS(
    "background-color",
    "rgb(34, 36, 33)",
  );
  await expect(
    page.getByRole("heading", { name: "My portfolio", exact: true }),
  ).toBeVisible();
});
