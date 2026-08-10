# Assistant Tool Registry

The old persona and MCP-design files have been consolidated into one runtime boundary under `apps/api/app/tools/`. There is no external MCP server dependency.

The registry exposes allowlisted, typed wrappers for portfolio summary/performance, IPS compliance, portfolio/security quant, market series/freshness, macro releases, company research, sourced events, and ownership-filtered document search. Definitions include `name`, `version`, Pydantic input model, permission scope, read-only flag, confirmation requirement, timeout, cost class, and handler. Per-request tool count and cost-unit budgets are enforced. Unknown names are rejected; arbitrary SQL, dynamic imports, files, general network calls, secrets, broker automation, and order placement are not tools.

The assistant flow is:

```text
authorize user/portfolio
  -> resolve data cutoff and freshness
  -> reconstruct bounded conversation context
  -> let the configured model propose allowlisted read-only tools
  -> validate arguments and invoke bounded deterministic tools
  -> retrieve scoped document passages
  -> assemble calculated evidence and citations
  -> require structured claims with valid evidence IDs and validate numerical grounding
  -> answer or explicitly report missing data
```

Tool traces are persisted with assistant messages and exposed to the UI. Any future state-changing tool must use a separate permission and explicit confirmation; the current registry is read-only.
