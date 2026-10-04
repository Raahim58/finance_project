# Allocation verification: confirmed failures and deferred fixes

Recorded 2026-10-04. Investigation only; the fixes below are not implemented.

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
