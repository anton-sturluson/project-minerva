import { expect, test } from "@playwright/test";

test("a delayed initial ledger cannot overwrite a saved cash entry", async ({
  page,
}) => {
  await page.clock.install({ time: new Date("2026-10-17T16:00:00Z") });
  const accountId = "00000000-0000-4000-8000-000000000093";
  const empty = { balance: "0", currency: "USD", holdings: [], entries: [] };
  let reads = 0;
  let releaseOldRead: (() => void) | undefined;
  const oldRead = new Promise<void>((resolve) => {
    releaseOldRead = resolve;
  });
  await page.route("**/api/accounts", (route) =>
    route.fulfill({
      json: [
        {
          id: accountId,
          name: "Synthetic ledger ordering",
          base_currency: "USD",
          created_at: "2026-10-16T00:00:00Z",
        },
      ],
    }),
  );
  await page.route("**/ledger", async (route) => {
    reads += 1;
    const read = reads;
    if (read === 1) await oldRead;
    await route.fulfill({
      json:
        read <= 2
          ? empty
          : {
              ...empty,
              balance: "100",
              entries: [
                {
                  id: 1,
                  kind: "opening_cash",
                  effective_date: "2026-10-16",
                  amount: "100",
                  currency: "USD",
                  note: "",
                  security: null,
                },
              ],
            },
    });
  });
  await page.route("**/cash", (route) => route.fulfill({ json: { id: 1 } }));
  await page.goto("/#activity");
  await expect.poll(() => reads).toBe(2);
  await page.getByText("Record cash", { exact: true }).click();
  await page.getByLabel("Cash amount", { exact: true }).fill("100");
  await page
    .getByRole("button", { name: "Save cash entry", exact: true })
    .click();
  await expect(page.getByTestId("cash-balance")).toHaveText("USD 100.00");
  const oldResponse = page.waitForResponse((response) =>
    response.url().endsWith("/ledger"),
  );
  releaseOldRead!();
  await (await oldResponse).finished();
  await page.waitForLoadState("networkidle");
  await expect(page.getByTestId("cash-balance")).toHaveText("USD 100.00");
  await expect(
    page.getByText("Cash entry saved.", { exact: true }),
  ).toBeVisible();
});
