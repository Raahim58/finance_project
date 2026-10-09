import { expect, test } from "@playwright/test";

// Browser-only contract fixtures. Nothing here is bundled into the app or seeded.
const portfolio = { id: "overview-test", name: "Contract test portfolio", base_currency: "PKR", source_mode: "manual", provider_name: "ManualPortfolioProvider", is_default: true, history_complete: true, archived_at: null };
const second = { ...portfolio, id: "second-test", name: "Second contract portfolio", is_default: false };
const evidence = { id: "chunk:test", document_id: "test-doc", page_number: 2, title: "Contract test filing", source_name: "Test company filing", source_url: "https://example.test/filing.pdf", text: "A retained test passage for the browser contract." };
const event = { id: "test-event", event_key: "raw:test-event", raw_event_id: "test-event", normalized_event_id: "n", title: "Stored test announcement", occurred_at: "2026-10-01T12:00:00Z", event_type: "announcement", source_document_type: "announcement", materiality: "high", freshness_status: "recent", factors: [], subjects: [{ subject_key: "TEST" }], evidence: [evidence] };
const price = { symbol: "TEST", close: "125.50", change: "5.50", change_percent: "4.58", trade_date: "2026-10-01", volume: 1234567, source: "Observed test prices" };
const market = { snapshot: { snapshot_date: "2026-10-01", index_name: "Test market index", index_value: "65432.10", index_change: "250.10", index_change_percent: "0.38", total_volume: 9876543, total_value: "123456789", source: "Observed test snapshot" }, top_gainers: [price], top_losers: [{ ...price, symbol: "LOSS", change_percent: "-1.20" }], top_volume: [price], sectors: [{ sector: "Test sector", trade_date: "2026-10-01", advancers: 23, decliners: 11, unchanged: 4, source: "Observed test breadth" }] };
const regime = { regime: "mixed", method: "rule_based_v1", method_note: "Classification of retained structured test observations.", dimensions: { rates: { status: "rising", value: 12, unit: "%", series_name: "Test policy rate", effective_date: "2026-09-30" }, market_breadth: { status: "positive", advancers: 23, decliners: 11, source: ["Observed test breadth"], trade_date: "2026-10-01" } }, stress_signals: ["rates"], suggested_scenario_ids: [] };

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("psx_ai_token", `offline.${btoa(JSON.stringify({ sub: "overview-test-user" }))}.test`));
  let selectedId=portfolio.id;
  await page.route("**/api/**", async route => {
    const url = new URL(route.request().url());
    const path = url.pathname.replace(/^\/api/, "");
    const current = path.includes(second.id) ? second : portfolio;
    let body: unknown = [];
    if (path === "/auth/me") body = { full_name: "Contract Reader", email: "reader@example.test" };
    else if(path.endsWith("/select-default")){selectedId=path.split("/")[2];body={...second,is_default:true};}
    else if (path === "/portfolios") body = [portfolio, second].map(row=>({...row,is_default:row.id===selectedId}));
    else if (path === "/market/overview") body = market;
    else if (path === "/market/freshness") body = { market_data_mode: "auto", refresh_seconds: 60, is_stale: false, exchange_session_status: "closed", trade_date_status: "current", latest_trade_date: "2026-10-01" };
    else if (path === "/market/companies") body = [{ id: "company-test", symbol: "TEST", name: "Test catalog company", is_active: true }];
    else if (path === "/macro/regime") body = regime;
    else if (path === "/research/event-feed") body = { events: [event], next_cursor: null };
    else if (path.endsWith("/summary")) body = { portfolio: current, total_value: current.id === second.id ? "9876543" : "1234567", day_change: "1234", day_change_percent: "0.10", cash_balance: "123456.70", holdings: [{ symbol: "TEST" }], valuation_complete: true, unpriced_symbols: [], data_source: "Observed test prices", data_freshness_date: "2026-10-01" };
    else if (path.endsWith("/performance")) body = [{ value_date: "2026-09-28", cumulative_twr_percent: "0" }, { value_date: "2026-09-29", cumulative_twr_percent: "1.25" }, { value_date: "2026-09-30", cumulative_twr_percent: null }, { value_date: "2026-10-01", cumulative_twr_percent: "2.50" }];
    else if (path.endsWith("/ips/compliance")) body = { status: "PASS", compliant: true, checks: [], violations: [], not_evaluated: [] };
    else if (path === "/monitoring/alerts") body = [{ classification: "monitoring_warning", status: "open" }];
    else if (path.endsWith("/event-intelligence")) body = { portfolio_id: current.id, portfolio_name: current.name, valuation_complete: true, coverage: { holdings: 1, priced_holdings: 1 }, events: [{ event, companies: [{ symbol: "TEST", relationship_kind: "direct" }], potentially_affected_weight: "0.25" }] };
    else if (path === "/documents/test-doc/pages/2") body = { title: evidence.title, page_number: 2, text: evidence.text };
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });
});

test("overview uses API values and preserves financial context", async ({ page }) => {
  const mutations: string[] = [];
  page.on("request", request => { if (request.method() !== "GET") mutations.push(request.url()); });
  await page.setViewportSize({ width: 1536, height: 1024 });
  await page.goto("/dashboard");
  await expect(page.getByText("65,432.1", { exact: true })).toBeVisible();
  await expect(page.getByText("PKR 1,234,567", { exact: true })).toBeVisible();
  await expect(page.getByText("+2.50%", { exact: true })).toBeVisible();
  await expect(page.getByText("25.00% potentially exposed")).toBeVisible();
  await expect(page.getByText("1 active monitoring warning")).toBeVisible();
  await expect(page.getByText("Mandate: within evaluated limits")).toBeVisible();
  await page.getByRole("button", { name: "Volume", exact: true }).click();
  await expect(page.getByRole("link", { name: /#1 by traded volume/ })).toHaveAttribute("href", "/companies/TEST");
  await expect(page.getByText("25.00% potentially exposed")).toHaveCount(0);
  expect(mutations).toEqual([]);
  await page.screenshot({ path: "test-results/overview-desktop.png", fullPage: true });
});

test("portfolio selection, company search and original source page work", async ({ page }) => {
  await page.goto("/dashboard");
  await expect(page.getByText("PKR 1,234,567", { exact: true })).toBeVisible();
  await page.getByLabel("Selected portfolio context").selectOption(second.id);
  await expect(page.getByText("PKR 9,876,543", { exact: true })).toBeVisible();
  await expect(page.getByText("PKR 1,234,567", { exact: true })).toHaveCount(0);
  await page.getByRole("button",{name:"Find a company",exact:true}).click();
  await page.getByRole("textbox",{name:"Find a company",exact:true}).fill("TEST");
  await expect(page.getByRole("link", { name: "TEST Test catalog company" })).toHaveAttribute("href", "/companies/TEST");
  await page.getByRole("textbox",{name:"Find a company",exact:true}).press("Escape");
  await page.getByText("View evidence", { exact: false }).first().click();
  await page.getByRole("button", { name: "Read page 2" }).click();
  await expect(page.getByRole("dialog", { name: "Source page" })).toBeVisible();
  await expect(page.getByRole("dialog").getByText(evidence.text)).toBeVisible();
});

test("missing data remains unavailable and mobile does not overflow", async ({ page }) => {
  await page.route("**/api/market/overview", route => route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "Market service offline" }) }));
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/dashboard");
  await expect(page.getByText(/Market snapshot unavailable.*Market service offline/)).toBeVisible();
  await expect(page.getByText("65,432.1", { exact: true })).toHaveCount(0);
  await expect(page.getByText("PKR 1,234,567", { exact: true })).toBeVisible();
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.getByRole("button", { name: "Open primary navigation" }).click();
  await expect(page.getByRole("dialog", { name: "Primary navigation" })).toBeVisible();
  await page.getByRole("button", { name: "Close primary navigation", exact: true }).last().click();
  await page.screenshot({ path: "test-results/overview-mobile.png", fullPage: true });
});
