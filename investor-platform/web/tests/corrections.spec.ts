import { expect, test } from "./fixtures";

test("reviews a correction, retries a lost response once, preserves audit, and voids it", async ({
  page,
  request,
}) => {
  const account = await (await request.get("/api/account")).json();
  const created = await request.post(`/api/accounts/${account.id}/cash`, {
    data: {
      request_key: crypto.randomUUID(),
      kind: "deposit",
      amount: "100",
      currency: "USD",
      effective_date: new Date().toISOString().slice(0, 10),
      note: "Synthetic correction fixture",
    },
  });
  expect(created.ok()).toBe(true);
  const entry = await created.json();
  const path = `/api/accounts/${account.id}/ledger`;
  const before = await (await request.get(path)).json();
  await page.goto("/");
  await page
    .getByRole("button", { name: `Correct entry ${entry.id}`, exact: true })
    .click();
  await page.getByLabel("Replacement cash amount").fill("200");
  await page
    .getByLabel("Correction reason")
    .fill("Synthetic broker reconciliation");
  await page
    .getByRole("button", { name: "Preview correction", exact: true })
    .click();
  await expect(page.getByLabel("Correction preview")).toContainText(
    "Synthetic broker reconciliation",
  );
  expect((await (await request.get(path)).json()).balance).toBe(before.balance);
  let lose = true;
  await page.route(`**/entries/${entry.id}/correction`, async (route) => {
    const response = await route.fetch();
    if (lose) {
      lose = false;
      await route.abort();
    } else await route.fulfill({ response });
  });
  await page
    .getByRole("button", { name: "Confirm correction", exact: true })
    .click();
  await expect(page.getByRole("alert")).toContainText("draft is preserved");
  await page
    .getByRole("button", { name: "Confirm correction", exact: true })
    .click();
  await expect(
    page.getByText("Correction saved. Original retained in audit history.", {
      exact: true,
    }),
  ).toBeVisible();
  await page.reload();
  const after = await (await request.get(path)).json();
  expect(Number(after.balance)).toBeCloseTo(Number(before.balance) + 100, 6);
  const audit = after.corrections.find(
    (c: { original: { id: number } }) => c.original.id === entry.id,
  );
  expect(audit.original.amount).toBe(entry.amount);
  expect(after.corrections.length).toBe(before.corrections.length + 1);
  await page
    .getByText(`Correction history (${after.corrections.length})`, {
      exact: true,
    })
    .click();
  await expect(
    page.getByRole("heading", {
      name: `Replaced entry #${entry.id}`,
      exact: true,
    }),
  ).toBeVisible();
  await page
    .getByRole("button", {
      name: `Correct entry ${audit.replacement.id}`,
      exact: true,
    })
    .click();
  await page.getByLabel("Correction action").selectOption("void");
  await page.getByLabel("Correction reason").fill("Remove synthetic deposit");
  await page
    .getByRole("button", { name: "Preview correction", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Review void", exact: true }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page
    .getByRole("button", { name: "Confirm correction", exact: true })
    .click();
  await expect(
    page.getByText("Correction saved. Original retained in audit history.", {
      exact: true,
    }),
  ).toBeVisible();
});

test("rejects an overdraft correction and requires a fresh review after another write", async ({
  page,
  request,
}) => {
  const account = await (await request.get("/api/account")).json();
  const payload = {
    request_key: crypto.randomUUID(),
    kind: "deposit",
    amount: "100",
    currency: "USD",
    effective_date: new Date().toISOString().slice(0, 10),
    note: "Stale preview fixture",
  };
  const entry = await (
    await request.post(`/api/accounts/${account.id}/cash`, { data: payload })
  ).json();
  await page.goto("/");
  await page
    .getByRole("button", { name: `Correct entry ${entry.id}`, exact: true })
    .click();
  await page.getByLabel("Replacement type").selectOption("withdrawal");
  await page.getByLabel("Replacement cash amount").fill("999999999999");
  await page.getByLabel("Correction reason").fill("Synthetic rejection check");
  await page
    .getByRole("button", { name: "Preview correction", exact: true })
    .click();
  await expect(page.getByRole("alert")).toContainText("negative");
  await expect(page.getByLabel("Replacement cash amount")).toHaveValue(
    "999999999999",
  );
  await page.getByLabel("Replacement type").selectOption("deposit");
  await page.getByLabel("Replacement cash amount").fill("101");
  await page
    .getByRole("button", { name: "Preview correction", exact: true })
    .click();
  await expect(page.getByLabel("Correction preview")).toBeVisible();
  await request.post(`/api/accounts/${account.id}/cash`, {
    data: { ...payload, request_key: crypto.randomUUID(), amount: "1" },
  });
  await page
    .getByRole("button", { name: "Confirm correction", exact: true })
    .click();
  await expect(page.getByRole("alert")).toContainText("Records changed");
  await page.getByRole("button", { name: "Edit draft", exact: true }).click();
  await page
    .getByRole("button", { name: "Preview correction", exact: true })
    .click();
  await expect(page.getByLabel("Correction preview")).toBeVisible();
  await page
    .getByRole("button", { name: "Confirm correction", exact: true })
    .click();
  await expect(
    page.getByText("Correction saved. Original retained in audit history.", {
      exact: true,
    }),
  ).toBeVisible();
});
