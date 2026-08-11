import { expect, test } from "@playwright/test";

const email = process.env.E2E_DEMO_EMAIL ?? "portfolio.manager@example.com";
const password = process.env.E2E_DEMO_PASSWORD ?? "DemoPass123!";

test("demo decision workflow stays semantically connected", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  await expect(page.getByText("Decision support only", { exact: true })).toBeVisible();

  await page.goto("/portfolios");
  await expect(page.getByText("1 Investor profile", { exact: true })).toBeVisible();
  const workspace = page.getByRole("link", { name: /Open workspace/ }).first();
  const href = await workspace.getAttribute("href");
  expect(href).toMatch(/^\/portfolios\/[^/]+\/overview$/);
  const portfolioBase = href!.replace(/\/overview$/, "");

  await page.goto(`${portfolioBase}/quant`);
  await page.getByRole("button", { name: "Efficient frontier" }).click();
  await expect(page.getByText(/comparison frontier/)).toBeVisible();
  await expect(page.getByRole("img", { name: /Portfolio markers/ })).toBeVisible();

  await page.goto(`${portfolioBase}/scenarios`);
  await expect(page.getByRole("heading", { name: "Versioned stress templates" })).toBeVisible();
  await expect(page.getByText(/Regime:/)).toBeVisible();
  await expect(page.getByText("Broad PSX drawdown", { exact: true })).toBeVisible();

  await page.goto("/recommendations");
  const review = page.getByRole("link", { name: /Review in Build|Revise linked proposal/ }).first();
  await expect(review).toHaveAttribute("href", /\/build\?recommendation=/);

  await page.goto("/market");
  await expect(page.getByText("Data mode", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Macro and market regime" })).toBeVisible();
});
