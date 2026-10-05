import { expect, test } from "./fixtures";

test("shows a closed synthetic trade and recovers a scorecard load failure", async ({
  page,
  request,
}) => {
  const account = await (await request.get("/api/account")).json();
  const base = `/api/accounts/${account.id}`;
  const date = new Date().toISOString().slice(0, 10);
  const ticker = `S${crypto.randomUUID().slice(0, 8).toUpperCase()}`;
  const cash = await request.post(`${base}/cash`, {
    data: {
      kind: "deposit",
      amount: "100",
      effective_date: date,
      currency: "USD",
      request_key: crypto.randomUUID(),
    },
  });
  expect(cash.ok()).toBe(true);
  for (const [kind, price] of [
    ["buy", "20"],
    ["sell", "30"],
  ]) {
    const result = await request.post(`${base}/trades`, {
      data: {
        kind,
        price,
        quantity: "1",
        ticker,
        exchange: "TEST",
        currency: "USD",
        effective_date: date,
        request_key: crypto.randomUUID(),
      },
    });
    expect(result.ok()).toBe(true);
  }
  await page.route("**/statistics", (route) =>
    route.fulfill({
      status: 503,
      json: { detail: "Scorecard temporarily unavailable." },
    }),
  );
  await page.goto("/");
  await expect(page.getByRole("alert")).toContainText(
    "Scorecard temporarily unavailable",
  );
  await page.unroute("**/statistics");
  await page.getByRole("button", { name: "Retry scorecard" }).click();
  await expect(page.getByTestId("win-rate")).toBeVisible();
  await expect(page.getByRole("alert")).toBeHidden();
  await page.getByText("Closed positions", { exact: true }).click();
  await expect(
    page
      .getByLabel("Closed positions", { exact: true })
      .getByRole("row")
      .filter({ hasText: ticker }),
  ).toContainText("10.00");
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});
