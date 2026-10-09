import { expect, test } from "@playwright/test";
const portfolio = {
  id: "p1",
  name: "Growth",
  is_default: true,
  archived_at: null,
};
const userMessage = {
  id: "u1",
  role: "user",
  content: "Explain my context",
  context: { page: "workspace", portfolio_id: "p1", portfolio_name: "Growth" },
  execution_id: "r1",
  outcome: null,
  created_at: "2026-10-03T00:00:00Z",
  evidence: {},
};
const canonical = {
  conversation_id: "c1",
  message_id: "a1",
  answer: "**Saved answer** with [source](https://example.test/filing)",
  uncertainty: [],
  calculated_evidence: [],
  source_citations: [
    { title: "Filing", source_url: "https://example.test/filing" },
  ],
  freshness_warnings: [],
  tool_trace: [],
  synthesis: { mode: "llm_tool_loop" },
  created_at: "2026-10-03T00:00:01Z",
};
test("persistent streaming drawer survives navigation, closure, switching and reload", async ({
  page,
}) => {
  let submissions = 0,
    started = false,
    complete = false,
    eventSubscriptions = 0;
  await page.addInitScript(() =>
    localStorage.setItem(
      "psx_ai_token",
      "header." + btoa(JSON.stringify({ sub: "offline-user" })) + ".signature",
    ),
  );
  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url()),
      path = url.pathname.replace(/^\/api/, "");
    let body: unknown = [];
    if (path === "/auth/me")
      body = { id: "offline-user", email: "fixture@example.test" };
    else if (path === "/portfolios") body = [portfolio];
    else if (path === "/portfolios/p1/risk-flags") body = { flags: [] };
    else if (path === "/portfolios/p1/summary") body = { portfolio, holdings: [], total_value: "0" };
    else if (path === "/preferences") body = { default_llm_provider: "zai" };
    else if (path === "/assistant/workspace/conversations")
      body = {
        items: [
          {
            id: "c1",
            title: "Saved chat",
            active_run:
              started && !complete
                ? { execution_id: "r1", status: "running" }
                : null,
          },
          { id: "c2", title: "Other chat", active_run: null },
        ],
        next_cursor: null,
      };
    else if (
      path.includes("/assistant/workspace/conversations/") &&
      path.endsWith("/messages")
    )
      body = {
        items:
          path.includes("/c1/") && started
            ? [
                userMessage,
                ...(complete
                  ? [
                      {
                        id: "a1",
                        role: "assistant",
                        content: canonical.answer,
                        context: userMessage.context,
                        execution_id: "r1",
                        outcome: "completed",
                        created_at: canonical.created_at,
                        evidence: { sources: canonical.source_citations },
                      },
                    ]
                  : []),
              ]
            : [],
        next_cursor: null,
        active_run:
          path.includes("/c1/") && started && !complete
            ? { execution_id: "r1", status: "running" }
            : null,
        runs: [],
        summary: null,
        summary_failure: null,
      };
    else if (path === "/assistant/runs") {
      submissions++;
      started = true;
      body = { execution_id: "r1", conversation_id: "c1", status: "running" };
    } else if (path === "/assistant/runs/r1/events") {
      eventSubscriptions++;
      const after = Number(url.searchParams.get("after") ?? 0);
      const events = [
        {
          sequence: 1,
          kind: "text_delta",
          payload: { text: "Provisional stream" },
        },
        {
          sequence: 2,
          kind: "activity",
          payload: { text: "Generating answer" },
        },
        ...(complete
          ? [
              {
                sequence: 3,
                kind: "terminal",
                payload: { status: "completed", response: canonical },
              },
            ]
          : []),
      ].filter((e) => e.sequence > after);
      const data =
        events
          .map((e) => `id: ${e.sequence}\ndata: ${JSON.stringify(e)}\n\n`)
          .join("") +
        (complete
          ? `event: snapshot\ndata: ${JSON.stringify({ status: "completed", response: canonical })}\n\n`
          : "");
      await route.fulfill({ contentType: "text/event-stream", body: data });
      return;
    }
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(body),
    });
  });
  await page.goto("/settings");
  await page.getByLabel("Open Assistant").click();
  await expect(page.getByText(/Growth/)).toBeVisible();
  await page.getByLabel("Message Assistant").fill("Explain my context");
  await page.getByRole("button", { name: "Send", exact: true }).click();
  await expect(
    page.getByText("Provisional stream", { exact: true }),
  ).toBeVisible();
  expect(submissions).toBe(1);
  await page.getByLabel("Message Assistant").fill("Keep this draft");
  await page.getByLabel("Close Assistant").click();
  await page.getByRole("link", { name: "Monitoring", exact: true }).click();
  await page.getByLabel("Open Assistant").click();
  await expect(page.getByLabel("Message Assistant")).toHaveValue(
    "Keep this draft",
  );
  await expect(
    page.getByText("Provisional stream", { exact: true }),
  ).toBeVisible();
  await page.getByLabel("Expand Assistant").click();
  await expect(page.getByRole("dialog")).toHaveClass(/assistant-expanded/);
  await page.getByLabel("Saved chats").click();
  await page.getByRole("button", { name: "Other chat", exact: true }).click();
  await page.getByLabel("Saved chats").click();
  await page.getByRole("button", { name: /^Saved chat ·/ }).click();
  await expect(page.getByLabel("Message Assistant")).toHaveValue(
    "Keep this draft",
  );
  await page.reload();
  await page.getByLabel("Open Assistant").click();
  await expect(
    page.getByText("Provisional stream", { exact: true }),
  ).toBeVisible();
  expect(submissions).toBe(1);
  complete = true;
  await expect(page.getByText("Saved answer", { exact: true })).toBeVisible();
  await expect(
    page.getByRole("link", { name: "source", exact: true }),
  ).toHaveAttribute("href", "https://example.test/filing");
  await expect(
    page.getByText("Provisional stream", { exact: true }),
  ).toHaveCount(0);
  expect(eventSubscriptions).toBeGreaterThan(1);
  expect(submissions).toBe(1);
  await page.screenshot({ path: "test-results/assistant-desktop.png" });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole("dialog")).toHaveCSS("width", "390px");
  await page.screenshot({ path: "test-results/assistant-mobile.png" });
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
});
