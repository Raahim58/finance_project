# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: ui-inspect.spec.ts >> inspect authenticated workstation
- Location: ui-inspect.spec.ts:5:5

# Error details

```
TimeoutError: page.waitForURL: Timeout 30000ms exceeded.
=========================== logs ===========================
waiting for navigation until "load"
============================================================
```

# Page snapshot

```yaml
- generic [ref=e2]:
  - complementary "Primary navigation" [ref=e3]:
    - link "PX PSX Workstation Portfolio intelligence" [ref=e4] [cursor=pointer]:
      - /url: /dashboard
      - generic [ref=e5]: PX
      - generic [ref=e6]:
        - strong [ref=e7]: PSX Workstation
        - generic [ref=e8]: Portfolio intelligence
    - generic [ref=e9]:
      - generic [ref=e10]:
        - paragraph [ref=e11]: Workspace
        - link "Overview" [ref=e12] [cursor=pointer]:
          - /url: /dashboard
      - generic [ref=e19]:
        - paragraph [ref=e20]: Investment
        - link "Portfolios" [ref=e21] [cursor=pointer]:
          - /url: /portfolios
        - link "Markets" [ref=e27] [cursor=pointer]:
          - /url: /markets
        - link "Research" [ref=e32] [cursor=pointer]:
          - /url: /research
        - link "Assistant" [ref=e37] [cursor=pointer]:
          - /url: /assistant
      - generic [ref=e42]:
        - paragraph [ref=e43]: Oversight
        - link "Recommendations" [ref=e44] [cursor=pointer]:
          - /url: /recommendations
        - link "Monitoring" [ref=e48] [cursor=pointer]:
          - /url: /monitoring
        - link "Activity" [ref=e52] [cursor=pointer]:
          - /url: /activity
      - generic [ref=e56]:
        - paragraph [ref=e57]: System
        - link "Settings" [ref=e58] [cursor=pointer]:
          - /url: /settings
    - generic [ref=e63]:
      - strong [ref=e64]: Decision support only
      - text: No broker connection or trade execution
  - generic [ref=e65]:
    - banner [ref=e66]:
      - generic [ref=e67]:
        - generic [ref=e68]: Investment workspace
        - generic [ref=e70]: Source and freshness labels active
      - generic [ref=e72]:
        - link "Search evidence" [ref=e73] [cursor=pointer]:
          - /url: /research
        - link "Open monitoring" [ref=e77] [cursor=pointer]:
          - /url: /monitoring
        - link "Investor desk" [ref=e80] [cursor=pointer]:
          - /url: /settings
    - main [ref=e81]:
      - main [ref=e82]:
        - generic [ref=e83]:
          - link "Back to PSX Workstation home" [ref=e84] [cursor=pointer]:
            - /url: /
            - generic [ref=e85]: PX
            - generic [ref=e86]:
              - strong [ref=e87]: PSX Workstation
              - generic [ref=e88]: Evidence-led investing
          - generic [ref=e89]:
            - paragraph [ref=e90]: Private investment workspace
            - heading "Opening the demo workstation." [level=1] [ref=e91]
            - paragraph [ref=e92]: Establishing the same authenticated browser session used by normal login.
            - status [ref=e94]:
              - generic [ref=e95]: Authenticating and loading the demo portfolio…
          - paragraph [ref=e96]: Analysis only · No automated trading
        - complementary [ref=e97]:
          - generic [ref=e98]:
            - paragraph [ref=e99]: Workstation principles
            - paragraph [ref=e100]: The number, the source, and the decision context stay together.
          - generic [ref=e101]:
            - generic [ref=e102]:
              - heading "Structured values" [level=2] [ref=e103]
              - paragraph [ref=e104]: Portfolio and market numbers come from database queries.
            - generic [ref=e105]:
              - heading "Cited narrative" [level=2] [ref=e106]
              - paragraph [ref=e107]: Document research retains source and page metadata.
            - generic [ref=e108]:
              - heading "Explicit uncertainty" [level=2] [ref=e109]
              - paragraph [ref=e110]: Missing, stale, or unsupported data remains visible.
```

# Test source

```ts
  1  | import { test } from "@playwright/test";
  2  | 
  3  | test.use({ channel: "chrome" });
  4  | 
  5  | test("inspect authenticated workstation", async ({ page }) => {
  6  |   test.setTimeout(240_000);
  7  |   const token = process.env.DEMO_ACCESS_TOKEN;
  8  |   if (!token) throw new Error("DEMO_ACCESS_TOKEN is required");
  9  |   const consoleErrors: string[] = [];
  10 |   const failedResponses: Array<{ url: string; status: number }> = [];
  11 |   page.on("console", message => { if (message.type() === "error") consoleErrors.push(message.text()); });
  12 |   page.on("response", response => {
  13 |     if (response.status() >= 400) failedResponses.push({ url: response.url(), status: response.status() });
  14 |   });
  15 | 
  16 |   await page.goto(`http://127.0.0.1:3000/demo-login?token=${encodeURIComponent(token)}`, { waitUntil: "domcontentloaded" });
> 17 |   await page.waitForURL(/\/portfolios\/[^/]+\/overview/, { timeout: 30_000 });
     |              ^ TimeoutError: page.waitForURL: Timeout 30000ms exceeded.
  18 |   const portfolioId = page.url().match(/\/portfolios\/([^/]+)/)?.[1];
  19 |   if (!portfolioId) throw new Error("Demo login did not resolve a portfolio");
  20 | 
  21 |   const routes = [
  22 |     ["overview", `/portfolios/${portfolioId}/overview`],
  23 |     ["build", `/portfolios/${portfolioId}/build`],
  24 |     ["quant", `/portfolios/${portfolioId}/quant`],
  25 |     ["risk", `/portfolios/${portfolioId}/risk`],
  26 |     ["scenarios", `/portfolios/${portfolioId}/scenarios`],
  27 |     ["research", `/portfolios/${portfolioId}/research`],
  28 |     ["activity", `/portfolios/${portfolioId}/activity`],
  29 |     ["ips", `/portfolios/${portfolioId}/ips`],
  30 |     ["portfolios", "/portfolios"],
  31 |     ["markets", "/market"],
  32 |     ["global-research", "/research"],
  33 |     ["monitoring", "/monitoring"],
  34 |     ["dashboard", "/dashboard"],
  35 |   ] as const;
  36 |   const results: Array<Record<string, unknown>> = [];
  37 |   for (const [name, route] of routes) {
  38 |     const started = Date.now();
  39 |     await page.goto(`http://127.0.0.1:3000${route}`, { waitUntil: "domcontentloaded" });
  40 |     await page.waitForTimeout(name === "quant" || name === "risk" ? 8_000 : 4_000);
  41 |     results.push(await page.evaluate(({ name, route, elapsed }) => ({
  42 |       name,
  43 |       route,
  44 |       elapsed,
  45 |       title: document.title,
  46 |       heading: document.querySelector("h1")?.textContent?.trim() ?? null,
  47 |       bodyText: document.body.innerText.slice(0, 500),
  48 |       horizontalOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth,
  49 |       scrollWidth: document.documentElement.scrollWidth,
  50 |       clientWidth: document.documentElement.clientWidth,
  51 |     }), { name, route, elapsed: Date.now() - started }));
  52 |     await page.screenshot({ path: `/tmp/psx-ui-${name}.png`, fullPage: true });
  53 |   }
  54 | 
  55 |   await page.setViewportSize({ width: 390, height: 844 });
  56 |   for (const [name, route] of routes.filter(([name]) => ["overview", "quant", "markets", "monitoring"].includes(name))) {
  57 |     await page.goto(`http://127.0.0.1:3000${route}`, { waitUntil: "domcontentloaded" });
  58 |     await page.waitForTimeout(4_000);
  59 |     results.push(await page.evaluate(({ name, route }) => ({
  60 |       name: `${name}-mobile`,
  61 |       route,
  62 |       horizontalOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth,
  63 |       scrollWidth: document.documentElement.scrollWidth,
  64 |       clientWidth: document.documentElement.clientWidth,
  65 |     }), { name, route }));
  66 |     await page.screenshot({ path: `/tmp/psx-ui-${name}-mobile.png`, fullPage: true });
  67 |   }
  68 | 
  69 |   console.log("UI_INSPECTION=" + JSON.stringify({ portfolioId, results, consoleErrors, failedResponses }));
  70 | });
  71 | 
```