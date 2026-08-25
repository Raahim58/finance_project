## Problem Statement

Once Company Research and Assistant have migrated to the Canonical Intelligence Context, retaining the legacy security intelligence path indefinitely would preserve two competing contracts, duplicate context assembly, and invite future consumers to use the wrong source. Removal must nevertheless be deliberate: it is the final Phase 7 pass, it depends on verified consumer migration, and it may proceed only after explicit user confirmation.

## Solution

After Phase 7B passes and the user explicitly approves removal, audit every internal and external consumer, remove the legacy security intelligence implementation and obsolete contract surface, update registrations and tests, and prove that Canonical Intelligence Context is the sole intelligence assembly path. Keep the change narrowly scoped to retirement; unrelated architecture cleanup remains separate.

## User Stories

1. As a Company Research user, I want research to continue working after legacy removal, so that retirement causes no regression.
2. As an Assistant user, I want company questions and Security Fit to continue using grounded canonical context, so that removal does not weaken answers.
3. As a portfolio investor, I want selected-portfolio ownership and IPS enforcement preserved, so that legacy removal cannot leak or blend portfolio data.
4. As a user without complete data, I want missing, stale, refreshing, partial, failed, and not-evaluated states preserved, so that cleanup does not erase uncertainty.
5. As a user awaiting ingestion, I want refresh-pending and terminal rebuild behavior preserved, so that retirement does not break context updates.
6. As an auditor, I want stable evidence IDs and reproducibility receipts preserved, so that historical and new outputs remain traceable.
7. As an operator, I want deficiency routing and ingestion deduplication preserved, so that removing legacy assembly does not create duplicate work.
8. As a developer, I want one intelligence context contract, so that new behavior has one authoritative seam.
9. As a developer, I want obsolete tool registrations and schemas removed, so that the legacy path cannot be invoked accidentally.
10. As a developer, I want generated client contracts updated if the external route changes, so that stale types do not advertise removed behavior.
11. As a maintainer, I want deliberate compatibility handling for any public route, so that removal is explicit rather than an accidental breaking change.
12. As a maintainer, I want tests to fail if a legacy import, registration, route, or response shape returns, so that the old path stays retired.
13. As the product owner, I want the final deletion blocked on my explicit approval, so that parity can be reviewed before irreversible cleanup.

## Implementation Decisions

- This is implementation pass 3 of 3.
- Work may not begin until Phase 7B has been reported and the user has explicitly confirmed legacy removal.
- Before deletion, inventory route handlers, tool registrations, imports, tests, generated contracts, frontend callers, documentation, and operational references associated with the legacy security intelligence path.
- Verify Company Research and Assistant use the Canonical Intelligence Context contract in production routing, not only in tests.
- Remove the legacy security intelligence assembler and any helper logic that exists solely for its obsolete response shape.
- Remove or replace obsolete tool definitions and route registrations so no hidden consumer can continue to call the legacy contract.
- Preserve candidate evaluation, proposal persistence, deterministic portfolio comparison, scenario analysis, and other intelligence behavior that is not part of legacy context assembly.
- Do not delete a broader intelligence module merely because it contains the legacy function; separate surviving responsibilities before removal when necessary.
- Preserve Canonical Intelligence Context versioning, evidence IDs, freshness/readiness states, deficiency lifecycle, ownership checks, and compact receipts.
- If an externally visible route is retired, update generated contracts and callers in the same pass. Do not leave a silent route that returns a different shape under the old name unless explicit compatibility behavior was approved.
- Update documentation to name Canonical Intelligence Context as the sole shared context contract for Company Research and Assistant.
- Do not combine this retirement with unrelated god-module refactors, Redis decisions, UI redesign, broker work, or advanced quant changes.

## Testing Decisions

- Test through the highest authenticated Company Research and Assistant seams after removal.
- Rerun the complete Phase 7A contract suite and Phase 7B consumer-conformance suite.
- Prove company-only, selected-portfolio Company Research, company-only Assistant, and Security Fit behavior after deletion.
- Prove selected-portfolio ownership and confirmed-IPS requirements remain enforced.
- Prove deterministic exact values, bounded RAG evidence, normalized relevant events, stable evidence IDs, and zero LLM context construction remain unchanged.
- Prove degraded context, deficiency routing, asynchronous ingestion, terminal rebuild, active update, and inactive lazy refresh remain unchanged.
- Add a source-level guard that fails when the removed legacy symbol, obsolete tool registration, obsolete response contract, or legacy route registration reappears.
- Regenerate and type-check client contracts when route/schema removal affects them.
- Run backend tests, frontend tests, static type checks, and targeted end-to-end decision workflow coverage proportionate to the removed surface.
- Confirm no tests continue to import the legacy implementation directly; tests should exercise canonical external behavior.

## Out of Scope

- Any work from Phase 7A or 7B that has not already passed review.
- New Context Builder capabilities.
- New Company Research or Assistant features.
- Phase 8 reasoning redesign.
- Phase 9 Research UX redesign.
- Phase 10 intelligence UI integration.
- Phase 11 persistent Assistant shell.
- Redis adoption, unrelated module refactors, dead-widget removal, or broker scaffolding.
- Advanced quant features or trade execution.

## Further Notes

- The issue is specified in advance but implementation remains explicitly approval-gated.
- “Ready for agent” means the specification is complete; it does not override the required user confirmation before deletion begins.
- The final report must identify everything removed, everything deliberately retained, compatibility changes, and the verification commands/results.
