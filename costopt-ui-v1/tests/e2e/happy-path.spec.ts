import { expect, test } from "@playwright/test";

test("complete mock analysis journey", async ({ page }) => {
  test.setTimeout(60_000);
  await page.goto("/#/analyses");
  await page.getByRole("button", { name: "New Analysis" }).click();
  await expect(page.getByRole("heading", { name: "Add data" })).toBeVisible();
  await page.getByRole("button", { name: "Load Sample Fieldglass Data" }).click();
  await page.getByRole("button", { name: "Review" }).click();
  await page.getByRole("button", { name: "Confirm Extracted Data" }).click();
  await page.getByRole("button", { name: "Continue to Check Data" }).click();
  await page.getByRole("checkbox", { name: /reviewed the remaining warnings/i }).check();
  await page.getByRole("button", { name: "Continue to Setup" }).click();
  await page.getByLabel("India").check();
  await page.getByRole("button", { name: "Run Analysis" }).click();
  await expect(page.getByRole("heading", { name: "Review recommendations" })).toBeVisible();
  await page.getByRole("tab", { name: "Recommendations" }).click();
  await page.getByRole("button", { name: "Review" }).first().click();
  await page.getByLabel("Action").selectOption("accepted");
  await page.getByRole("button", { name: "Save Decision" }).click();
  await page.getByRole("button", { name: "Continue to Approval" }).click();
  await page.getByRole("button", { name: "Approve" }).click();
  await page.getByRole("button", { name: "Confirm Decision" }).click();
  await expect(page.getByRole("heading", { name: "Approved analysis report" })).toBeVisible();
});
