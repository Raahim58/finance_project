## Problem Statement

After the Canonical Intelligence Context module exists, Company Research and Assistant will still rely on their legacy, independently assembled shapes. Users will not receive the benefit of one evidence contract until both consumers are migrated and verified together. The migration must preserve deterministic truth, portfolio ownership, selected-IPS semantics, citations, missing-data honesty, and existing fallback behavior without beginning the later Research or Assistant UX redesigns.

## Solution

Migrate Company Research and Assistant to consume the versioned Canonical Intelligence Context contract created in Phase 7A. Company Research requests company-only context by default and adds Portfolio Relevance only for one explicitly selected portfolio. Assistant requests the sections required by its intent; Security Fit requires Portfolio Relevance. Both consumers retain the same evidence IDs, section states, refresh lifecycle, and exact-vs-RAG separation. Verify shared-contract use and report before any legacy removal.

## User Stories

1. As a Company Research user, I want the company view to use the canonical company-only context, so that its facts and evidence match Assistant.
2. As a Company Research user without a selected portfolio, I want no portfolio or IPS information included, so that general research is not personalized accidentally.
3. As a Company Research user with a selected portfolio, I want Portfolio Relevance calculated for exactly that portfolio, so that ownership, exposure, and mandate fit are accurate.
4. As a user with several portfolios, I want changing the selected portfolio to rebuild only portfolio-dependent sections, so that company evidence remains reusable while relevance updates.
5. As a user, I want Company Research to cite the same evidence IDs that Assistant sees, so that the two surfaces cannot disagree about provenance.
6. As an Assistant user, I want structured and narrative context selected according to my current question, so that retrieval remains relevant and bounded.
7. As an Assistant user asking a company-only question, I want an answer without unnecessary portfolio or IPS data, so that the analysis stays focused.
8. As an Assistant user asking Security Fit, I want one selected portfolio and confirmed IPS required, so that the answer cannot fall back to global user preferences.
9. As an Assistant user, I want the selected portfolio's IPS to supply every investment preference and constraint, so that personal fit uses the correct mandate.
10. As an Assistant user, I want ordinary Security Fit questions to retrieve relevant company evidence and events automatically, so that retrieval does not depend on special trigger words.
11. As an Assistant user, I want Security Fit to use normal safe planning rounds, so that it no longer bypasses the standard evidence-planning path.
12. As an Assistant user, I want exact values to remain deterministic, so that the model interprets but never calculates portfolio truth.
13. As an Assistant user without an external LLM, I want the deterministic fallback to consume the same canonical context, so that grounding does not depend on provider configuration.
14. As an Assistant user with an external LLM, I want synthesis grounded only in allowed evidence IDs from the canonical context and approved tool results, so that claims remain traceable.
15. As an Assistant user, I want LLM and deterministic-fallback mode explicit, so that I know how the answer was produced.
16. As a user, I want stale or missing context displayed honestly while ingestion proceeds, so that neither consumer implies current completeness.
17. As a user, I want an active Company Research view to update once linked ingestion reaches terminal state, so that newly available evidence appears without manual repetition.
18. As an Assistant user, I want the original answer and its evidence preserved when refreshed data becomes available, so that the audit trail is not rewritten.
19. As an Assistant user, I want refreshed data delivered as a linked follow-up, so that I can see what changed.
20. As a returning user, I want an inactive company view or conversation marked for lazy refresh, so that current data appears when I return without wasting background work.
21. As an auditor, I want each consumer to persist the compact context receipt used for its output, so that results can be reproduced.
22. As a security-conscious user, I want every portfolio-dependent request to enforce ownership before returning any partial context, so that migration cannot weaken access controls.
23. As a developer, I want contract drift detected automatically, so that Company Research and Assistant cannot silently start depending on different context shapes.
24. As a developer, I want the legacy path retained during migration, so that parity can be measured before deletion.

## Implementation Decisions

- This is implementation pass 2 of 3 and is blocked until Phase 7A is reviewed and approved.
- Company Research and Assistant are the only consumers migrated in this pass.
- Company Research requests Company Intelligence: company facts, market/risk, sector, macro, relevant events, RAG evidence when a research purpose exists, and missing-data states.
- Company Research adds Portfolio Relevance only when one portfolio is explicitly selected.
- Portfolio Relevance always uses exactly one user-owned portfolio and that portfolio's selected confirmed IPS.
- Assistant intent determines the requested context sections. The Assistant does not receive a giant all-sections context by default.
- Assistant Security Fit requires Portfolio Relevance and therefore a selected portfolio and confirmed IPS.
- Investment fields from user-level application preferences are removed from Company Research and Assistant intelligence inputs. Application-only settings may still select an LLM provider or notification behavior.
- Security Fit no longer receives a zero-round planning exception.
- Security Fit automatically requests company-direct RAG evidence and relevant normalized events even when the question does not contain narrative trigger words.
- Context construction remains deterministic and performs zero LLM calls. Assistant synthesis remains outside the Context Builder.
- Deterministic calculations, evidence IDs, allowed-claim validation, numerical grounding, and fallback behavior remain authoritative.
- The consumer-facing synthesis mode remains explicit.
- Company Research may replace an active intelligence result after a terminal refresh rebuild because it presents current research state.
- Assistant never silently mutates an earlier answer. Refreshed context creates a linked follow-up while preserving the original message and receipt.
- Both consumers store or reference the compact reproducibility receipt from the context build rather than persisting a duplicate permanent context object.
- The legacy security intelligence path remains available throughout this pass for parity checks and rollback.
- No Research page redesign, Company page redesign, persistent chat shell, or new market/portfolio intelligence surface is introduced here.

## Testing Decisions

- Test migration through the highest existing authenticated Company Research and Assistant request seams.
- Reuse existing company-overview, intelligence, RAG, event-intelligence, portfolio ownership, IPS, and Assistant orchestration tests as prior art.
- Add a contract-conformance suite that runs representative Company Research and Assistant requests and asserts the shared context version and section semantics.
- Prove company-only research contains no portfolio or IPS section.
- Prove selected-portfolio research uses exactly that portfolio and its selected confirmed IPS.
- Prove portfolio switching invalidates portfolio-dependent sections without changing stable company evidence IDs.
- Prove Security Fit fails safely without the required portfolio/IPS scope.
- Prove Security Fit performs normal safe planning rounds.
- Prove an ordinary fit question retrieves symbol-scoped company evidence and normalized relevant events without special narrative wording.
- Prove unrelated company evidence is rejected.
- Prove user-level investment preference fields are absent from intelligence inputs.
- Prove deterministic fallback and LLM-grounded synthesis consume equivalent canonical facts and evidence IDs.
- Prove LLM validation rejects unknown evidence IDs, unsupported numerical claims, and advice-like claims without evidence.
- Prove section failures produce degraded consumer output rather than a false complete state.
- Prove active Company Research refresh replacement, inactive lazy refresh, preserved Assistant message history, and linked Assistant refresh follow-up.
- Prove second-user portfolio access is rejected before partial context is returned.
- Compare legacy and canonical outputs on representative fixtures and document deliberate differences, particularly normalized events, RAG evidence, IPS sourcing, and missing-data states.
- Do not remove or disable the legacy path in any test or production routing during this pass.

## Out of Scope

- Removing the existing security intelligence implementation or endpoint.
- Phase 8 synthesis-schema redesign beyond what is required to consume canonical context safely.
- Phase 9 Research UX reconstruction and automatic “what changed / why it matters” presentation redesign.
- Phase 10 Market, Company, and Portfolio event-intelligence UI integration.
- Phase 11 floating Assistant, drawer, thread switching, and cross-page chat shell.
- Multi-portfolio comparison in one context.
- New ingestion providers, worker replacement, or scheduler redesign.
- Redis selection or permanent context-vector storage.
- Broker automation or trade execution.

## Further Notes

- Stop and report after Company Research and Assistant are migrated and shared-contract verification passes.
- Phase 7C may begin only after explicit user confirmation.
- The legacy path is intentionally retained even if unused by normal consumers so rollback and final approval remain possible.
