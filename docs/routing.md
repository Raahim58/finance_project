# Deterministic first-pass routing

`query -> route label(s) -> retrieval contract -> bounded tool plan -> evidence packet -> answer model`

The model no longer decides the first-pass evidence. `apps/api/app/ai/routing/` is pure (no model, DB or tool access):

| Module | Responsibility |
|---|---|
| `types.py` | `Route` (16 labels), `Block` types, `RouterInput`, `RouteDecision`, `RetrievalContract`, `PlanStep`, `BudgetLog` |
| `rules.py` | Rule router: normalized text + resolved entities + selected-portfolio flag -> one primary and up to two secondary routes. Score below 2.0 -> `general_fallback`. |
| `contracts.py` | Per-route required / optional / forbidden blocks, secondary contribution, portfolio context policy, entity cap, hard call cap |
| `planner.py` | Contract -> concrete read-tool calls (the only block-to-tool mapping), budget enforcement, routing record |

Called from `ai/company_packet.initial_calls`; `tool_loop._prepare_evidence` stores `checkpoint['routing']` (route, blocks, budget log, gaps; never the question text).

## Assumptions
- Entities come from server-resolved identity (symbols in the question, explicit instrument, owned portfolio holdings), never from model output.
- Exact values still come from SQL-backed tools; `evidence_search` returns document text only.
- Budget is a hard cap on first-pass **tool calls** (`min(contract.max_calls, allowance - 4)`; 4 calls stay reserved for follow-ups). Drop order: secondary/optional tail, optional search, required tail, required search. Required blocks cut by budget are recorded as gaps. Token-level packet trimming is not implemented.
- Blocks with no data source (`technical_levels`, `analyst_revisions`, `earnings_calendar`) are reported in `missing_data` (`source: route_contract`) so the answer must state the data is missing.
- A selected portfolio is automatic context unless the route's contract says `never` (market brief, technical setup, definitions) or the request is `company_only`.
- The model keeps the full tool catalog for follow-up calls. Restricting follow-ups to the contract is a later phase.
- Taxonomy, rules and contracts stay in code (versioned by git). Only the *log* and *eval runs* are tables.
- Tie-break classifier (`routing/classifier.py`, `ASSISTANT_ROUTE_CLASSIFIER_ENABLED`, default on): called only when no rule reaches the minimum score (and it is not a follow-up / one-word input) or the top two routes are within 0.5. One no-tool, no-thinking provider call on the execution ledger and budget, offered only the candidate labels. It returns a label + confidence; unknown labels, bad JSON, confidence < 0.5 or provider errors keep the rule decision. It never chooses tools. Cost: one extra model call on ambiguous questions.
- Eval set: `routing/eval_cases.py` (expectations are author-chosen, not user-labelled).

## Tables (migration `0036_routing_log`)
`route_decisions` (one row per execution, unique), `route_budget_logs`, `routing_eval_runs`. Rows hold route labels, block names and scores only: no question text, evidence or keys. Writes are best-effort and never fail a question.

```bash
cd apps/api && .venv/bin/alembic upgrade head
```

## Evaluate
```bash
cd apps/api
.venv/bin/python -m app.jobs.evaluate_routing                       # rules only, offline
ZAI_API_KEY=... .venv/bin/python -m app.jobs.evaluate_routing --live --provider zai \
  --model glm-4.5-flash --output /tmp/routing-live.jsonl [--persist]   # makes paid provider calls
```
The key is read from the environment variable at call time and is never printed or stored.

## Validate
```bash
cd apps/api
DATABASE_URL=sqlite:////tmp/psx-routing-tests.sqlite EMBEDDING_BACKEND=hash .venv/bin/pytest app/tests/test_routing.py app/tests/test_routing_classifier.py app/tests/test_company_packet.py app/tests/test_evidence_output_contract.py -q
```
Seed data is not needed.
