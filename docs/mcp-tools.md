# Assistant Tool Registry

The old persona and MCP-design files have been consolidated into one runtime boundary under `apps/api/app/tools/`. There is no external MCP server dependency.

The registry exposes allowlisted, typed wrappers for portfolio summaries/compliance, portfolio quant and risk, market freshness, and ownership-filtered research/document search. Definitions include `name`, `version`, Pydantic input model, permission scope, read-only flag, confirmation requirement, timeout, cost class, and handler. Unknown names are rejected; arbitrary SQL, dynamic imports, files, general network calls, secrets, broker automation, and order placement are not tools.

The assistant flow is:

```text
authorize user/portfolio
  -> resolve data cutoff and freshness
  -> invoke bounded deterministic tools
  -> retrieve scoped document passages
  -> assemble calculated evidence and citations
  -> validate numerical grounding
  -> answer or explicitly report missing data
```

Tool traces are persisted with assistant messages and exposed to the UI. Any future state-changing tool must use a separate permission and explicit confirmation; the current registry is read-only.
