# Assistant Tool Registry

The old persona and MCP-design files have been consolidated into one runtime boundary under `apps/api/app/tools/`. There is no external MCP server dependency.

The registry exposes allowlisted, typed wrappers for portfolio summary/performance, IPS compliance, portfolio/security quant, market series/freshness, macro releases, company research, sourced events, and ownership-filtered document search. Definitions include `name`, `version`, Pydantic input model, permission scope, read-only flag, confirmation requirement, timeout and handler. The 12-call execution cap remains; cost classes and cost-unit budgets have been removed. Unknown names are rejected; arbitrary SQL, dynamic imports, files, general network calls, secrets, broker automation, and order placement are not tools.

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

## Workload bounds (2026-10-03)

- `market.latest`: one latest database observation with date, close and provenance.
- `market.series`: 30 rows by default, explicit maximum 260. SQL fetches at most limit + 1 rows; `has_more` and the continuation date identify older pages. `remaining` is null when the total has not been counted. Other analytical readers retain complete history.
- `documents.discover`: default five, maximum ten documents per page, up to three 320-character matching excerpts per document; discovery citation quotes share the same bound. Excerpts identify truncation and retain source IDs/links. Full text remains accessible through `documents.read` (maximum 20 physical pages or 20 chunks per call), without truncating stored evidence. Discovery still scores the ownership-filtered corpus; this change bounds returned evidence, not corpus-wide search cost.
- `allocation.verify`: maximum 20 proposal legs, 100 allowed IDs and 100 held/proposed instruments. Existing aligned-history calculation is preserved; comparison output now declares sample dates, return observations and annualization. No silently shortened risk window. The existing 20-second async tool timeout returns `tool_timeout`; PostgreSQL statement timeouts bound individual queries. A running Python worker thread cannot be forcibly terminated by asyncio cancellation, so this is a response deadline, not a hard CPU kill. Verification is read-only.
- Existing checkpoint cost fields are ignored for compatibility, and allowance text is regenerated without cost units. No migration is required. The input estimator and token policies are unchanged.

Verification (from repository root):

```sh
cd apps/api
DATABASE_URL='sqlite+pysqlite:///:memory:' EMBEDDING_BACKEND=hash .venv/bin/python -m pytest app/tests/test_tool_registry.py app/tests/test_canonical_market.py app/tests/test_read_tool_contracts.py app/tests/test_company_read_tools.py app/tests/test_document_read_tools.py app/tests/test_allocation_verification_tools.py app/tests/test_tool_loop_*.py app/tests/test_assistant_execution.py app/tests/test_allocation_calculation.py app/tests/test_evidence_projection.py -q
```

No new dependencies, seeds or database migration required. Deployment uses the existing API rebuild/restart workflow; these local changes are not yet deployed.
