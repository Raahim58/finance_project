## Problem Statement

Company Research and Assistant currently assemble overlapping security context through different paths. The existing security intelligence concept is shallow, returns loosely structured nested data, omits parts of the required intelligence picture, mixes portfolio-independent company research with portfolio-specific fit, and has no durable way to report missing inputs to the existing ingestion machinery. Users need one deterministic, request-scoped intelligence context that reads current authoritative data, preserves evidence provenance, remains useful under partial data, and never becomes a giant permanent context vector.

## Solution

Build a versioned Canonical Intelligence Context module as a read-only assembler. A consumer requests only the sections required for its purpose. The module returns bounded structured sections, stable evidence identifiers, per-section freshness/readiness, and structured deficiencies. A separate durable bridge deduplicates those deficiencies, lets the ingestion coordinator select existing workers, and rebuilds an active context once after all linked ingestion work reaches a terminal state. The first pass introduces this module and its tests without migrating Company Research or Assistant.

## User Stories

1. As a company researcher, I want company-only intelligence context without portfolio or IPS data, so that general company research is not accidentally personalized.
2. As a portfolio investor, I want company context optionally enriched for one selected portfolio, so that portfolio relevance uses the mandate I actually selected.
3. As an Assistant user asking about Security Fit, I want the selected portfolio and its confirmed IPS required, so that fit is never inferred from a global preference.
4. As a user with multiple portfolios, I want exactly one selected portfolio evaluated per context request, so that different mandates are never blended.
5. As an investor, I want the confirmed portfolio-specific IPS to be the sole source of investment preferences, so that risk tolerance, horizon, liquidity, objectives, benchmarks, preferences, exclusions, and constraints remain coherent.
6. As an investor without a confirmed IPS, I want portfolio-specific context to state that the IPS is missing, so that analysis does not invent a mandate.
7. As a researcher, I want exact company facts to come from structured authoritative records, so that RAG passages are not substituted for numerical truth.
8. As a researcher, I want market and risk metrics to retain their calculation cutoffs and provenance, so that I can judge whether they are usable.
9. As a researcher, I want sector context to include canonical sector comparisons, so that the company can be evaluated relative to its sector.
10. As a researcher, I want relevant sector narrative intelligence represented through Events and RAG evidence, so that it is available without being duplicated across sections.
11. As a researcher, I want the macro regime and its underlying observations represented separately, so that a classification is distinguishable from observed inputs.
12. As a researcher, I want only material, relevant events included, so that context is not flooded by an unbounded feed.
13. As a researcher, I want only the best few passages relevant to the supplied question or research purpose, so that RAG evidence is concise and grounded.
14. As a Company Intelligence consumer, I want predefined deterministic research purposes for recent changes, outlook, risks, and drivers, so that automatic research does not require an LLM-generated query.
15. As an Assistant consumer, I want the current user question to drive narrative retrieval, so that evidence is relevant to what was asked.
16. As an auditor, I want every decision-relevant fact and metric to carry a stable evidence ID, classification, source, and as-of value, so that later consumers cite the same evidence.
17. As an auditor, I want unchanged underlying evidence to retain the same evidence ID across builds, so that provenance is stable.
18. As a user, I want each context section to report its own freshness and readiness, so that monthly fundamentals are not judged by a daily-price rule.
19. As a user, I want freshness to follow the authoritative module's cadence, trading calendar, release frequency, and dependency state, so that old does not automatically mean stale.
20. As a user, I want one unavailable section to degrade rather than abort the entire context, so that useful evidence remains available.
21. As a user, I want invalid identity, invalid scope, or failed portfolio ownership to abort the build, so that partial results cannot bypass authorization.
22. As a user, I want context to return immediately when required data is stale or missing, so that I am not blocked by network ingestion.
23. As an ingestion operator, I want missing-data reports expressed as structured deficiencies, so that routing never depends on parsing prose.
24. As an ingestion operator, I want repeated equivalent deficiencies deduplicated, so that repeated page visits and Assistant questions do not flood queues.
25. As an ingestion operator, I want the ingestion coordinator to choose the worker, so that context consumers do not know queue names or provider details.
26. As a user, I want a reasonable refresh-pending status while data is fetched, so that I understand why the current context is degraded.
27. As a user, I want active context refreshed once after all linked ingestion jobs succeed, partially succeed, fail, or time out, so that I receive one coherent update rather than several partial rebuilds.
28. As a returning user, I want inactive contexts marked as having new data and rebuilt when reopened, so that abandoned requests do not consume unnecessary work.
29. As an auditor, I want failed ingestion to remain visible in the rebuilt context, so that successful sections do not hide unresolved gaps.
30. As a performance-conscious user, I want unchanged valid sections reused, so that revisiting a company does not repeat every calculation and retrieval.
31. As a user asking a new question one day later, I want stale or changed core sections rebuilt and a new question-specific evidence overlay retrieved, so that the answer is current without losing conversation history.
32. As an operator, I want the assembled context to remain reconstructable from authoritative stores, so that a cache never becomes the source of truth.
33. As an auditor, I want a compact build receipt containing evidence IDs, calculation runs, section states, contract version, and a content hash, so that use can be reproduced without duplicating all underlying records.
34. As a system owner, I want context construction to perform zero LLM calls, so that assembly remains deterministic, reproducible, and independently testable.

## Implementation Decisions

- Introduce one versioned Canonical Intelligence Context module as the highest testing seam.
- The module is request-scoped and read-only. It may query authoritative stores and existing deterministic calculation modules, but it may not ingest, write deficiencies, schedule work, or call an LLM.
- The context contract supports nine areas: portfolio, IPS, company facts, market/risk metrics, sector context, macro regime, relevant events, RAG evidence, and missing-data states.
- Consumers request only the required sections. Omitted sections are absent from the semantic context rather than treated as missing facts.
- Company Intelligence is company-only: it contains neither portfolio nor IPS.
- Portfolio Relevance is an optional bundle containing exactly one explicitly selected, user-owned portfolio, that portfolio's confirmed IPS, ownership/exposure, and the security-to-portfolio risk relationship.
- Security Fit requires Portfolio Relevance and therefore requires one selected portfolio and its confirmed IPS.
- Investment preferences are portfolio-specific IPS terms. User-level application preferences may control application behavior but must not enter investment context.
- The contract distinguishes current, stale, incomplete, missing, not evaluated, refreshing, and not requested states where applicable.
- Freshness policy remains owned by the authoritative module. Context aggregates the state and provenance rather than applying one global age threshold.
- Market and derived risk sections inherit freshness from their underlying observations and portfolio versions.
- RAG is restricted to unstructured document passages. Exact numerical values remain database queries or deterministic calculations.
- Narrative retrieval is purpose-dependent. Company Intelligence supplies stable predefined research purposes; Assistant requests may supply the user's question. No purpose means no RAG retrieval.
- RAG and Events return bounded, ranked results. Ranking considers direct entity relevance, materiality, source authority, query relevance, and freshness; older evidence may remain when still decision-relevant.
- Sector narrative evidence remains represented in Events or RAG evidence with sector relevance metadata rather than being duplicated inside the Sector section.
- Every decision-relevant item receives a stable evidence ID derived from its underlying fact, event, passage, observation, or calculation run rather than its context request.
- Soft section failures produce degraded context. Invalid company identity, invalid request scope, authorization failure, and portfolio ownership failure abort the build.
- The builder returns structured deficiencies with entity, category, observed state, expected coverage/freshness, reason, and urgency.
- A separate durable deficiency bridge records and deduplicates deficiencies. It delegates routing to the ingestion coordinator, which maps deficiencies onto existing current, historical, macro, report, and evidence workers.
- Context callers never select Celery queues, workers, or providers.
- The initial build returns available context immediately. It never waits for network ingestion.
- Linked ingestion work uses existing retries. Context construction does not retry ingestion.
- One rebuild is triggered after all linked work reaches a terminal success, partial, failed, or timed-out state. Active consumers receive the rebuilt context; inactive consumers are marked for lazy rebuild on return.
- The full assembled context is temporary. A compact reproducibility receipt may be persisted; short-lived caches may reuse valid sections but are not authoritative.
- Cache implementation technology is not selected in this pass. Reuse is governed by dependency identity, contract version, section purpose, selected portfolio/IPS version, and authoritative freshness state.
- This pass does not migrate Company Research or Assistant and does not remove the existing security intelligence path.

## Testing Decisions

- Test external behavior through the versioned Canonical Intelligence Context interface rather than its internal query helpers.
- Reuse the existing authenticated intelligence and Assistant test setup for users, portfolios, confirmed IPS versions, market observations, company facts, calculations, documents, and citations.
- Prove that company-only context does not query or expose portfolio and IPS sections.
- Prove that Portfolio Relevance uses exactly the selected user-owned portfolio and its confirmed IPS.
- Prove that Security Fit scope without a selected portfolio or confirmed IPS is rejected or reported according to the agreed request contract.
- Prove ownership enforcement with a second user and portfolio.
- Prove zero LLM/provider invocation during every context build.
- Prove exact-vs-RAG separation by ensuring document text never fills missing numerical facts.
- Prove bounded RAG and event admission, source/citation metadata, and deterministic purpose/query behavior.
- Prove stable evidence IDs across identical builds and changed IDs when the underlying version changes.
- Prove section-level freshness for trading-session, event-driven, daily, weekly, monthly, and reporting-period data.
- Prove soft section failure isolation and hard identity/authorization failure.
- Prove structured deficiency generation, deduplication, and routing without exposing worker names to callers.
- Prove immediate degraded return, linked ingestion terminal-state aggregation, single rebuild, active notification, inactive lazy rebuild, and honest failed-refresh state.
- Prove valid-section reuse and invalidation when price, portfolio, IPS, filing, event, macro, or retrieval inputs change.
- Prove the compact receipt can identify every item used without persisting a duplicate giant context object.
- Add performance instrumentation and a representative benchmark; report measured build time rather than asserting an unmeasured latency.

## Out of Scope

- Migrating Company Research to the new context contract.
- Migrating Assistant reasoning or tool planning to the new context contract.
- Removing the existing security intelligence path.
- Phase 8 LLM synthesis, contradiction analysis, implications, portfolio fit prose, or next-question generation.
- Phase 9 Research UX redesign.
- Phase 10 Market, Company, and Portfolio intelligence UI integration.
- Phase 11 persistent chat drawer and cross-page conversation shell.
- Replacing existing ingestion workers or schedulers.
- Selecting Redis or another permanent caching technology.
- Multi-portfolio comparison within one context request.
- Broker integration, trade placement, or password-based automation.

## Further Notes

- This is implementation pass 1 of 3. Stop and report after the module and tests are complete.
- Pass 2 may begin only after user review of this pass.
- The existing security intelligence path remains available throughout this pass.
- The domain glossary defines Company Intelligence, Portfolio Relevance, Security Fit, IPS, Investment Preference, and Application Preference.
