# Allocation verification: confirmed failures and deferred fixes

Recorded 2026-10-04. Targeted implementation authorized and completed locally; no commits, deployment or live-model checks. Beta/benchmark and shared-memory work remain deferred.

## Agreed GLM input fix

In `apps/api/app/tools/quant_tools.py`, normalize only `AllocationVerificationInput.proposal` before normal Pydantic validation:

1. If already an object, leave it unchanged.
2. If a string, parse JSON once and require the result to be an object.
3. Apply the existing strict `AllocationProposal`/`AllocationLeg` validation unchanged, including allowed sides, positive finite amounts, leg limits and forbidden extra fields.
4. Reject malformed JSON, non-object values and invalid proposals with concise field-specific feedback. Do not echo the full submitted payload.

Do not add prompt clutter, relax financial checks, parse arbitrary tool arguments or introduce recursive/double decoding. Add fixtures for valid objects, valid JSON object strings, malformed strings and invalid parsed proposals.

## Agreed model-output reduction

In `_verify_allocation`, provide a compact model-facing projection: legs, resulting weights, current/proposed headline metrics, constraint limits/values/statuses, missing checks, coverage warnings and citation identifiers. Remove repeated compliance trees, duplicated comparison material and per-instrument full missing-session date lists from model context. Preserve the full calculation and source evidence server-side using the existing persistence path; verify that path before changing the projection. Do not remove calculations or numerical validation. Budgets remain unchanged.

## Confirmed beta root cause (Oracle, read-only inspection)

Both `PSX Main Demo — Diversified` (86e5a852-259b-462e-9a8a-437645546f6c) and `PSX Decision Portfolio — Demo` (1144e501-28aa-48dc-927f-1738aa13b3ad) have selected IPS constraints `benchmark_symbol=HBL`, `performance_benchmark_symbol=HBL`, `target_beta=1.0`. Neither has a portfolio benchmark instrument ID.

The instrument master identifies HBL as Habib Bank Limited, type equity, not a market index. Canonical HBL coverage is one price dated 2026-08-12. Portfolio analytical samples contain 1,236 price dates from 2021-08-01 through 2026-08-12; HBL is missing 1,235 of those dates. No instruments were returned by a query for index/total_return_index types or symbols containing KSE.

`decision_market_inputs.benchmark_returns` returns None for missing sample dates; `compare_portfolio` cannot compute beta. The verification service then marks the selected beta constraint unavailable and rejects full acceptance. This is not a model/tool-call failure. Relaxing alignment cannot construct a return from a single observation. This beta calculation does not require a risk-free rate.

Actual remediation requires selecting an appropriate intended market benchmark and ingesting its genuine historical series, then checking aligned coverage and return basis. Do not silently substitute a benchmark, fabricate history, remove the beta limit or activate ingestion under this investigation scope.

### Locked post-ingestion follow-up

Use KSE-100 as the intended broad-market performance/beta benchmark for these demo portfolios after genuine historical index data is ingested and aligned coverage/return basis is verified. Update their selected benchmark configuration at that stage; do not replace HBL with another individual stock merely because it has history. No benchmark switch or ingestion is implemented now.

Additional Oracle inspection confirmed HBL has one legacy DPS price dated 2026-08-13 and three normalized observations on the same timestamp (one selected, two unselected), not hidden historical coverage. The selected timestamp is 2026-08-12 19:00 UTC. Date conventions should be checked when validating coverage. A legacy ticker PSX has one price; it is not a market-index substitute. No KSE/index series keys were found in market observations.

## Other observed issues, not authorized for implementation here

- Anthropic verification ran successfully, but subsequent request preflight blocked input. Failed preflight count/method/boundary were not saved; exact rejected token count is unknown. Large duplicated tool results contribute context load, but are not proof of its exact total.
- PostgreSQL shared-memory limit is 64 MiB; logs show failed 8 MiB shared-memory expansion. Oracle root disk had 26 GiB free when checked. A compose shared-memory change and PostgreSQL container recreation remain separate deployment work.
- Separate arithmetic feasibility, evaluated IPS breaches, unavailable IPS checks and evidence readiness rather than interpreting every non-pass as an unusable calculation. Do not label an unresolved candidate fully compliant.

No migration, seed, worker, model-call or deployment commands are needed to record this note. This file is uncommitted.


## Local implementation and verification

- Proposal normalization and strict validation are implemented in `tools/quant_tools.py`; field/type/message feedback excludes submitted input.
- Model-only verification projection is applied when producing provider result blocks. Full results for every verification call remain in the encrypted execution checkpoint (`allocation_calculations`, keyed by tool-call ID); latest full result also remains in `allocation_check`. Source provenance is retained in encrypted checkpoint evidence. Provider turns contain the compact projection and citation IDs.
- The verification service exposes `trade_feasibility`, `IPS_status`, and `evidence_status` independently. Existing full-acceptance and actionable-evidence gates remain unchanged. Calculated feasible candidates display with exact failed/unavailable checks, not as accepted recommendations.
- Rejected preflight counts are saved as `provider_input_preflight` diagnostic stages, without provider attempts or reservations. Synthetic limit messages do not increment provider usage and preserve available partial text/citations without dumping metadata.
- Canonical price date conversion and date filters use Asia/Karachi trading days. New observations retain explicit source trade dates. Existing midnight-local timestamps are correct and need no bulk rewrite; correcting their read conversion repairs displayed dates. Previously saved answers/analyses are historical snapshots and are not rewritten. Recompute dependent analyses when deploying/testing.

Setup uses the existing API virtualenv and web node_modules. No dependencies or migrations added. Run offline database tests against a disposable database only (the test fixture resets its schema):

```sh
DATABASE_URL=sqlite+pysqlite:///:memory: apps/api/.venv/bin/python -m pytest apps/api/app/tests/test_allocation_targeted_fixes.py apps/api/app/tests/test_assistant_scope_fixes.py apps/api/app/tests/test_canonical_market.py apps/api/app/tests/test_phase8_phase2_tool_loop.py apps/api/app/tests/test_phase11_workspace.py apps/api/app/tests/test_token_counting.py -q
cd apps/web
npm run typecheck
npm test -- components/AssistantChatMessage.test.tsx components/AssistantWorkspace.test.tsx app/assistant/page.test.tsx
npm run build
```

No live provider calls are part of these commands. Model limits, selected benchmark, ingestion and PostgreSQL configuration are unchanged.

Validation result: 91 focused backend tests and 11 frontend tests passed; TypeScript checks and production build passed. No live-provider verification performed.
