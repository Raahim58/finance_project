# Assistant and investment intelligence audit — 6 September 2026

## Decision

Keep the existing structured-data, portfolio, quant, and hybrid-retrieval foundations. Replace the oversized synthesis payload with a bounded decision packet, repair the response contract and validation, and connect the assistant to controlled read-only analytical workflows in a subsequent scope change.

For the full product, use **shared continuously maintained research + a mandate-led, on-demand portfolio decision workflow + bounded adaptive research when needed**. The four-stage Data → Processing → Research → Technical pipeline is a useful research pattern, but it is not a complete portfolio-management process by itself. Neither a single giant prompt nor a compulsory chain of specialist LLMs is the best default.

The objective is to evaluate what serves this investor's goals, constraints, horizon, and existing portfolio. Company attractiveness, portfolio suitability, position size, and entry timing are separate decisions. A company can be attractive while an additional allocation is unsuitable. A price signal can be unfavorable without invalidating a long-horizon thesis.

This is an audit and proposed design, not a change to runtime behavior or an investment recommendation. No paid LLM calls, trades, source refreshes, database migrations, or portfolio changes were made during the audit.

## Evidence and limits

Inspected the current source tree, CONTEXT.md, architecture/formula/source documentation, GitHub issue #5, assistant/provider/UI code, context and retrieval assembly, event normalization, financial extraction/screening, quant/comparison/optimization, and ingestion ledgers. Read PostgreSQL using SELECT queries and rebuilt MEBL canonical context in a read-only transaction. The old SQLite database has no invocation table and is not the source for these findings.

Existing tests run: `test_phase8_reasoning.py`, `test_assistant_orchestrator.py`, and `test_quant_domain.py`: **27 passed**, with one LangGraph deprecation warning. Additional isolated validator probes exposed defects described below. This was not a complete financial-model certification, penetration test, or browser/proxy incident replay. Provider-reported usage is recorded usage, not independently reconciled billing.

Current reconstructed context is not the exact historical prompt: full prompts are intentionally not persisted. Historical prompt bytes/token usage come from invocation diagnostics; section measurements come from a fresh build against stored data. Host worker liveness and every external source were not independently verified; old queue timestamps establish backlog, not its complete operational cause.

## The MEBL incident

Latest diagnosed request: “Analyze my existing MEBL holding. Should I add, hold, or reduce it?” The saved execution was `targeted`.

| Latest run, timestamps UTC | Input bytes | Provider-reported input tokens | Output tokens | Model latency |
|---|---:|---:|---:|---:|
| Synthesis, persisted 2026-09-03 20:00:43 | 700,683 | 320,002 | 1,638 | 29.646 s |
| Mechanical repair | 10,339 | 5,188 | 2,600 | 26.646 s |
| Combined | — | 325,190 | 4,238 | 56.292 s |

Both calls succeeded at the provider layer. The synthesis returned prose instead of the requested JSON. The repair returned a JSON object using `analysis` instead of the required `answer`; validation reported “Field required; Extra inputs are not permitted.” The application saved **Recommendation Synthesis Unavailable** and deterministic facts. An earlier repaired run failed portfolio ID, evidence, horizon, freshness, and numeric checks. Other attempts timed out during synthesis or repair.

All ten retained diagnostic attempts across six diagnosed executions total **1,295,299 reported input tokens** and **14,702 reported output tokens**. Three attempts have unknown token usage. These records are not a complete billing ledger, and unknown usage must not be interpreted as free.

The repair did not resend the entire 320k-token payload: it was roughly 5k input tokens. The primary cost already occurred in the first synthesis. Repeating the user request repeats that large synthesis. There is no general automatic provider retry loop in the inspected adapter, and the graph allows one mechanical repair. The frontend has one 401 session-repair retry, not a generic inference retry. The cause of each repeated user submission cannot be established from these records alone.

### Why the prompt is so large

A fresh canonical context measured 223,575 serialized bytes:

| Section | Bytes |
|---|---:|
| Events | 103,791 |
| Company facts | 84,971 |
| RAG evidence | 13,015 |
| Sector | 6,177 |
| Macro | 3,536 |
| IPS | 2,088 |
| Market/risk | 1,721 |
| Portfolio | 826 |

Remaining bytes are context metadata. These are JSON byte sizes, not estimated model tokens.

1. **Duplicate context inclusion.** `orchestrator.py` includes the canonical context and flattened evidence in `grounded_context`. `ReasoningEngine._deepen` also returns the same targeted context under `deep_context.contexts`, plus flattened evidence again. Reusing the Python context avoids rebuilding it but does not avoid serializing it twice into the model prompt.
2. **An outer row limit does not bound nested records.** One admitted event has **233 subjects and 224 source references**. `serialize_normalized_event` includes every source and subject. Six admitted events produced approximately 101.5 KB of event data. This requires a nested projection and a clustering-quality review; it is not solved by lowering RAG top-k.
3. **Facts and provenance are verbose.** Company-fact data is about 38.1 KB; its evidence registry adds 46.6 KB. The builder includes up to 100 official facts and 100 standardized facts without a question-specific metric/period projection, then the prompt repeats the registry.
4. **Validation internals enter the prompt.** The numeric allowlist for this reconstructed canonical context alone contains 2,341 entries, taking about 21.9 KB. These are not all useful financial facts: extraction scans arbitrary strings and generates numeric variants. The effective prompt can carry the list at multiple levels.
5. **No enforced inference token budget.** Provider `max_context_tokens` metadata is declared but unused. The engine does not measure input tokens against a request budget before calling the model. Tool-count/cost limits do not bound serialized context or model spend.
6. **History is count-bounded, not token-bounded.** Up to 12 message bodies can be included on conversation endpoints. This is a future cost amplifier, but the current one-shot page starts new requests and it is not established as the cause of this incident.

Relevant code: `apps/api/app/ai/orchestrator.py:921`, `apps/api/app/reasoning/engine.py:237`, `apps/api/app/services/context_builder.py:680`, `apps/api/app/services/event_intelligence_service.py:353`, `apps/api/app/reasoning/validation.py:28`.

### Why the response did not appear as expected

The generated advisory prose was intentionally withheld after failed validation; saved assistant rows contain fallbacks. Separately, the UI keeps only the latest result in component state. It does not recover prior saved messages after reload, navigation, or a lost HTTP response, and there is no durable run ID/status recovery flow in this page.

The POST spans context assembly, one or two model calls, and persistence. The provider timeout defaults to 30 seconds per HTTP operation; it is not an end-to-end deadline. Tool timeouts are checked after a synchronous handler returns, so they do not interrupt long work. This makes long requests and poor recovery predictable, but the precise browser/proxy failure in the reported incident remains unverified.

Persistence is fragmented: the user message is added early, and `get_decrypted_key_for_call` commits the session while updating key usage; the assistant answer and invocation diagnostics are committed later. Therefore it would be incorrect to say that all messages remain uncommitted until the end. The underlying issue is the absence of an explicit durable execution lifecycle and independently durable per-attempt accounting.

## Pipeline audit

| Layer | What exists | Limitation relevant to the objective |
|---|---|---|
| Investor mandate | Portfolio-specific confirmed IPS, required return, capacity/willingness, constraints and ownership | Preserve as the starting point. Do not turn the target return into a forecast or silently let narrative instructions change scope. |
| Holdings/performance | Ledger, cash, valuation, P&L, historical performance and modeled current-allocation analysis | Keep realized experience distinct from current-weights replay. Source mode and stale/unpriced positions must affect conclusions. |
| Market ingestion | Canonical observations, source priority, historical OHLCV, immutable artifacts, freshness/quality handling | Runtime coverage has substantial failures; current data and adjusted/total-return completeness cannot be assumed. |
| Company fundamentals | Official report extraction plus standardized secondary facts, provenance and OCR support | Limited taxonomy; canonical packet omits important reconciliation fields such as consolidated basis. It combines sources/versions without a clear selected fact per metric/period. |
| Valuation | Legacy derived ratios exist in research code | Canonical compatibility output currently returns empty growth/ratio dictionaries and explicitly unavailable valuation. P/E, P/B, sustainable profitability, and valuation ranges are not a complete connected assistant capability. |
| Screening | Sector grouping, growth/margin/liquidity score and completeness | Five-component heuristic, largely growth plus margin and volume. Not a comprehensive sector-specific quality/value/risk model. Latest rows can mix periods/versions because matching is not established before ratios/growth. |
| Macro | Source ladders, structured observations, rule-based regime and scenario routing | First matching series per dimension in key order; not a curated Pakistan/global transmission model. Different series frequencies and revisions need explicit handling. |
| News/documents | Hybrid PostgreSQL vector + lexical retrieval, source metadata, scope filtering, bounded chunks | Retain this foundation. Query decomposition, report-section targeting, contradiction preservation and source-specific freshness need better decision-oriented packaging. |
| Events | Classification, materiality, confidence, direct subjects and retained sources | Impact is explicitly `not_calculated`. Large clusters, possible cross-company merging, indirect exposures and event-to-cash-flow transmission remain blockers. |
| Quant | Returns, covariance shrinkage, CAPM, risk contributions, VaR/ES, frontier, optimization and stress | Useful existing modules, but historical-shrunk returns are not forward fundamental forecasts. Data/model sensitivity and costs matter. |
| Assistant orchestration | Targeted synthesis or sector discovery → reduction → deep context → synthesis → validation/repair | Context overexpansion, brittle routing, incomplete selection information, weak validators, and no durable UI execution recovery. |
| Monitoring | Stored rules, alerts, recommendations and deduplication | Monitoring must revisit a thesis and mandate using refreshed inputs; classification or a threshold alert alone is not a new investment thesis. |
| Evaluation | Unit/fixture tests, retrieval and event evaluation datasets | No comparable labeled Phase 8 research-quality dataset found in `app/evaluation`. Passing mocks did not predict the retained production failures. |

### Other concrete inconsistencies

- **Market-wide candidate reduction is under-informed.** Sector calls return only IDs. The reducer receives candidate IDs and portfolio context, not candidate financial records, sector rationales, or a complete macro comparison packet. It is asked to compare candidates without the evidence that explains their merits.
- **Discovery queries all matching historical price/snapshot rows and chooses latest in Python.** Use database latest-per-symbol queries. Peer discovery reads `MarketPrice` rather than the canonical `latest_price` accessor, creating a source-selection consistency risk to test rather than assuming the two remain equivalent.
- **Market-wide calls are unbounded in concurrency.** `asyncio.gather` launches every sector call; one exception makes the graph unavailable. Need a semaphore, per-sector budgets/status, and explicit incomplete coverage reporting. A large sector is not further chunked to a model budget.
- **Advice routing depends on phrasing.** `detect_intent` and `ADVICE_RE` are independent regex systems. “hold,” “add,” and informal “shud” do not consistently trigger the same evidence path as “should,” “buy,” or “reduce.” This affects quant/risk collection and fallback behavior even where deep context later adds IPS. Add a typed intent/scope contract and realistic paraphrase fixtures.
- **A screening snapshot is labeled risk metrics.** `_market_risk` takes `CompanyScreeningSnapshot.metrics_json`, which contains growth, margin and liquidity fields, as `risk_metrics`. Those fields are not volatility, beta, drawdown or marginal risk. Separate screening and actual calculated risk sections.
- **Event filtering happens after a limit.** `_events` requests the newest company-relevant rows, then removes those below medium materiality. Older material events can be excluded by newer low-materiality ones. Apply the desired predicate before limiting; preserve useful low-materiality company context separately.
- **Cluster breadth needs investigation.** Matching permits shared macro-factor keys and title similarity within a seven-day window, then unions subjects/sources. The observed large event may be a legitimate broad event or an overmerged cluster; membership counts alone do not prove which. Require issuer/action/period identity tests and bounded primary/corroborating/counterevidence references.
- **Freshness is uneven.** Company facts are marked CURRENT when any facts exist; this is not an expected-filing coverage check. Event freshness is stored during normalization and returned directly during serialization. Review aging at read time. Do not apply intraday SLAs to annual reports, or treat a newly fetched old annual series as current monthly macro evidence.
- **Phase scope is a real capability boundary.** GitHub #5 and architecture explicitly defer assistant execution of optimizers, scenarios, screeners and proposals. Existing backend analytics are not equivalent to an assistant that can evaluate new hypothetical allocations. Connecting read-only evaluations is a deliberate scope extension; executing trades remains a separate confirmed action.

## Grounding and prompt injection

There is no evidence that malicious prompt injection caused the 320k incident. Context injection/assembly is the confirmed cost problem. Nevertheless, retrieved filings, news, and historical messages are lower-trust model input and need an explicit instruction/data boundary.

The synthesis prompt says to use supplied facts but does not establish a robust untrusted-document contract. A document could contain instructions to change the conclusion or ignore the mandate. Putting text inside JSON does not make it trusted, and adding more agents can propagate contaminated summaries between stages.

The current validator both rejects useful text and accepts invalid claims:

- Numeric normalization strips the sign, so supplied `100` also validates `-100`.
- Percentage checks can accept a number with an incorrect percent unit.
- Numeric extraction scans narrative text and the user's question, allowing those strings to populate a purported structured-number allowlist.
- A valid ID in metadata does not validate an invented inline citation in the prose. The probe `[ev_fake]` passed when metadata contained `ev_real`.
- A bag of allowed numbers cannot bind an amount to a company, metric, fiscal period, currency, or calculation. Even individually valid numbers can be combined into a false claim.
- Mechanical repair receives no exact schema, no field-path detail from parse errors, and no focused authoritative values for repairing numerical mistakes. It must guess too much. The latest `analysis`/`answer` failure illustrates this.

Use typed facts with `(entity, metric, value, unit, period, source/version)` and precomputed display variants. Check inline citations and claim-to-fact references, keeping provenance out of the main prose payload where possible. Model-native structured output should be used where supported and verified, with a complete schema and bounded output. Supply a focused correction packet only for genuinely repairable errors. This does not imply that deterministic code should replace semantic investment judgment.

Keep ownership, IPS identity, tool permissions and numerical calculations outside the LLM. Treat document instructions as inert evidence, never as authorization. Test prompt-injection attempts embedded in news, reports and prior assistant text. The inspected key service already encrypts stored keys, returns masked metadata and decrypts server-side; preserve those boundaries. This audit did not establish a key leak.

## Operational blockers observed locally

- 7,748 documents, 29,091 chunks, 14,303 official financial facts, 18,320 standardized facts, and 27,593 macro observations exist. These are inventory counts, not proof of accuracy, freshness, or breadth per company.
- Price-history coverage: 6,090 complete, **1,258 failed**, 94 queued. These are coverage items, not 1,258 failed companies.
- Financial extraction: 1,244 complete, 142 partial, 2 failed. Report catalog and standardized-fundamental coverage also contain partial items.
- Six context ingestion work items remain queued; the oldest was requested August 25. Last update in that group was September 3.
- Latest recorded evidence-source success/attempt is August 16; four source states have consecutive failures. Latest inspected ingestion runs were macro refreshes on August 16. Source-specific ledgers must be assessed independently.
- Failed coverage items across datasets group into 1,171 `ValueError` and 91 `IntegrityError` cases. Inspect bounded error details and failed item keys before retrying; do not blindly republish the backlog.
- Sampled stored errors distinguish concrete failure classes: duplicate sector/date/source rows violating `uq_sector_stats_sector_date_source` during price-history work; DPS symbol-month responses with no validated OHLCV; report responses that were not PDFs; and native PDF extraction failures. Investigate atomic upserts/concurrent sector-stat updates for the first class, and classify genuinely empty/not-listed periods separately from transient download or parser failures for the second.
- The four failing evidence-source states record HTTP 403 for IMF news, NCCPL legal-framework and OPEC press releases, and HTTP 429 for GDELT. Source circuits/backoff and verified alternatives are needed; an LLM agent does not remove these source-access constraints. These are the recorded failures, not new live availability tests.
- Source documentation records NCCPL as manual-only following ordinary-access blocking, some macro adapters disabled/unverified, and annual fallbacks for missing series. Therefore automatic current foreign-flow coverage and complete high-frequency national/global macro coverage are not established.

Next operational investigation: scheduler heartbeat → reservation/publication → broker → worker lease → parser/validation → canonical selection → deficiency reconciliation. Verify each boundary with one bounded item and source SLA. Do not relaunch full backfills until duplicate-key and semantic-data failures are classified.

## Architecture comparison

These are design assessments, not benchmarked performance claims. RAG is a retrieval capability usable in every LLM architecture below; it is not the alternative to an agent.

| Approach | Analytical strengths | Cost/latency/reliability | Fit for this product |
|---|---|---|---|
| Current full context + synthesis + repair | Integrates already available evidence in one model answer; reuses canonical services | Measured expensive payloads and failed repairs; per-query duplication; brittle response transport | Repair as a baseline, not the final analytical capability |
| Your Data → Processing → Research → Technical chain | Clear stage ownership; useful briefings; separates thesis and entry condition | If each stage is an LLM, repeated context and sequential latency; early filtering mistakes propagate | Good shared research subsystem; add mandate, valuation, portfolio construction and monitoring |
| Compact deterministic workflow + one synthesis | Predictable, inexpensive, testable; exact calculations outside model | Bounded model spend; limited flexibility for unexpected missing evidence | Best default for normal holding, comparison, and portfolio questions |
| One adaptive tool-using research agent | Can investigate contradictions, choose additional documents and ask relevant analytical tools | Variable call count; tool/result budgets, loop termination and permission boundaries required | Escalation path for questions the fixed workflow cannot resolve |
| Specialist analyst agents + coordinator | Independent macro, sector/accounting, and portfolio perspectives on complex work | Higher total tokens and coordination burden; shared-model agreement is not independent evidence | Optional deep-research mode after evaluations establish incremental benefit |
| Deterministic ranking/optimizer without LLM | Reproducible constraints, allocation and risk arithmetic | Lowest language-model spend; transparent but input/model sensitive | Essential analytical component; insufficient for unstructured policy/news interpretation |
| Shared incremental research + routed portfolio workflow | Reuses company/event work across users while personalizing decisions; includes all previous components selectively | Background cost amortized; targeted requests stay small; requires provenance/versioning and invalidation | Recommended overall architecture |

Anthropic distinguishes predetermined workflows from model-directed agents and describes the cost/latency tradeoff of adding autonomy. This comparison follows that architectural distinction, not a claim that a particular agent framework improves investment results: [Building effective agents](https://www.anthropic.com/engineering/building-effective-agents).

## Proposed full investment process

### Shared research, updated when evidence changes

1. Ingest public market, filings, announcements, domestic/global macro and news through verified connectors. Maintain publication time, effective period, first-seen time, revisions, entity identity, source authority and content hashes.
2. Normalize exact values into structured tables. Reconcile consolidated/standalone basis, currency/scale, annual/quarterly/TTM periods, restatements, corporate actions and source disagreements. Retrieval returns text, not authoritative numerical outputs.
3. Build company and sector feature snapshots. Separate value, quality, growth, profitability, balance-sheet resilience, liquidity, and risk; preserve missing dimensions. Recompute only changed dependencies.
4. Produce bounded event assessments: what changed, evidence/counterevidence, exposed entities, plausible transmission channels, affected horizon, and unresolved facts. Distinguish direct issuer evidence from inferred sector exposure. Use LLMs for interpretation where they add value, not for downloading data or computing ratios.
5. Maintain reusable sector/company research notes with supporting fact IDs, evidence versions, and expiry/invalidation rules. A morning briefing is one view of this shared research, not a mandatory predecessor for every user query.

### Portfolio-specific decision on demand

1. Resolve the owned portfolio, confirmed IPS, requested horizon, cash flows/liquidity needs, restrictions, benchmark and required return. Clarify genuinely missing core information; never infer a new mandate from a document.
2. Identify the decision: explain performance; review a holding; evaluate an increment; compare alternatives; test goal feasibility; evaluate rebalancing; or explore the wider market. Do not run the complete investment process for a factual query.
3. Retrieve compact current portfolio/risk snapshots and relevant company/sector/event notes. A named holding should not trigger full-universe inference. Market discovery must transparently preserve eligible-universe coverage; any staged shortlisting must state its coverage and rules.
4. Run appropriate deterministic analytics. For an incremental investment, compare current allocation with plausible funded alternatives, including holding cash/no change. Use the same assumptions for all alternatives. Show effects on risk concentration, expected-return assumptions, goal shortfall, drawdown/stress exposure, liquidity and IPS compliance. Unsupported constraints remain explicit.
5. Evaluate valuation and thesis under documented scenarios. Historical-shrunk return estimates and CAPM remain labeled analytical models, not substitutes for forward company forecasts. Scenario probabilities and analyst assumptions need an approved provenance contract before entering optimization; do not invent them in an answer.
6. Apply optional entry/risk indicators when relevant to the investor's horizon and strategy. EMA/ATR should be deterministic calculations from validated OHLCV, with configured periods, adjustment basis, warm-up and data cutoff. A long-term portfolio question should not silently become an intraday timing strategy.
7. Synthesize one answer separating **company thesis**, **portfolio action/suitability**, **modeled sizing tradeoffs**, and **entry condition**, with horizon, confidence, sources, invalidation conditions and missing evidence. If additional research is necessary, enter a bounded tool loop and keep the original decision scope.
8. Save a durable answer/run receipt and monitor evidence/mandate changes. Generate linked updates only when something material changes; do not rerun every full prompt on a timer.

CFA Institute's portfolio-planning framework begins with the IPS, return/risk objectives and constraints; it does not reduce portfolio management to a collection of stock indicators: [Basics of Portfolio Planning and Construction](https://www.cfainstitute.org/insights/professional-learning/refresher-readings/2026/basics-of-portfolio-planning-and-construction).

### What “CFA-level” should mean in the implementation

Treat it as a process and evidence standard, not a marketing label or certification. Candidate analytical coverage includes:

- Investor needs: capacity versus willingness, nominal/real goal, horizon, contributions/withdrawals, liquidity, tax/turnover constraints, investment restrictions and benchmark.
- Financial analysis: accounting quality, recurring versus exceptional earnings, comparable periods, cash generation, leverage/coverage, profitability and reinvestment, using industry-appropriate definitions.
- Valuation: selected multiples and justified fundamentals; documented dividend, residual-income or cash-flow scenarios where supported. Banks require bank-specific accounting and capital/risk analysis rather than an industrial-company template. CFA Institute discusses the relationship of bank ROE, impairments and P/B in [bank performance reporting](https://blogs.cfainstitute.org/marketintegrity/2014/07/15/what-has-the-financial-crisis-taught-us-about-bank-performance-reporting/).
- Portfolio construction: marginal risk and diversification, objective feasibility, estimation uncertainty, scenario robustness, implementation costs and the effect of position size on the investor's entire portfolio.
- Monitoring: thesis changes, valuation changes, portfolio drift, mandate changes, realized versus modeled performance, and source/model failures.

For policy/geopolitical news, use an explicit chain: event → economic variable → company exposure → earnings/cash-flow/discount-rate channel → valuation scenario → portfolio effect. A headline's sentiment does not establish the direction of the stock's return. No verified exposure means that link remains a hypothesis.

For entry timing, ATR measures volatility and is not directional; EMA is a trend lens. An extended move may justify an entry-risk warning, but it does not prove how much news is priced in. Assess that claim using event timing, a relevant benchmark, valuation assumptions and available expectations. The existing event-study utility estimates historical abnormal returns and explicitly makes no causal claim. [Fidelity ATR guide](https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/atr).

## Incremental delivery and measurable acceptance

| Priority | Work | Acceptance |
|---|---|---|
| P0 | Compact canonical-to-LLM projection, single evidence registry, nested event/fact limits, token/cost preflight | Reproduce the MEBL fixture without live inference; assert no duplicate context, bounded nested records and explicit budget refusal/compaction |
| P0 | Exact output schema, useful field-path errors, one focused repair, typed numerical/citation checks | Latest prose/`analysis` failures covered; sign/unit/period/entity/inline-citation adversarial fixtures pass; no unsafe label substitution |
| P0 | Durable execution identity, immediate accepted/status response, final-result recovery and idempotency | Reload/disconnect/retry returns the same execution; partial usage is retained; no duplicate expensive POST execution |
| P0 | Investigate stalled freshness and history failures | One bounded item completes each operational boundary; age/completeness is visible; stale core inputs cannot masquerade as current |
| P1 | Correct fact selection, period/basis provenance, valuation/ratios, actual company-risk section | Known-company accounting fixtures reconcile; contradictory sources remain traceable; unsupported metrics remain unavailable |
| P1 | Fix macro series selection, event identity/breadth and nested evidence projection | Explicit country/series/frequency contracts; cross-company cluster regressions; policy/sector effects remain hypotheses until supported |
| P1 | Typed intent contract and controlled read-only portfolio evaluation | Paraphrases retrieve the same necessary evidence; current/proposed/no-change comparison uses one assumption set; no holdings mutation |
| P1 | Informative market reducer, bounded sector concurrency, database latest-row queries | Candidate merits reach reducer; full eligible coverage accounted for; failure/partial coverage explicit; budgets per mode |
| P2 | Shared versioned research and bounded adaptive investigation | Public research reused safely across portfolios; private data never enters shared cache; evidence change invalidates dependent notes |
| P2 | Technical-entry module and richer forward scenarios where useful | Added only after dataset integrity and out-of-sample usefulness are demonstrated; no automatic momentum veto on long-term decisions |
| P2 | Research-quality evaluation and monitoring | Horizon/mandate fit, counterevidence, citation support, false abstention, consistency, model sensitivity and portfolio tradeoffs evaluated |

Starting engineering targets, **not observed results or guaranteed savings**: ordinary targeted analysis 8k–20k input tokens, one synthesis, at most one focused repair, and a separately configured hard total budget. A 20k prompt would be about 94% smaller than the recorded 320k synthesis. Actual financial quality must be preserved in evaluations; do not achieve a token target by dropping core evidence. At equal token prices this reduces the input-token component proportionally, not necessarily total cost by the same amount.

Track cost per successfully delivered, grounded decision—not just per API call. Record per-stage latency, input/output/unknown/cache usage, payload section sizes, retries versus repairs, source freshness, retrieval coverage, invalidation reason, budget consumption and display/delivery status. Never record API keys or unrestricted full prompts. Cache public evidence and derived snapshots by source version; key personalized results by owner, portfolio/IPS/holdings versions, horizon and data cutoff. Token accounting and rate assumptions must remain model/provider specific.

Benchmark the compact baseline, fixed staged workflow and adaptive workflow on the same frozen evidence and user scenarios. Include existing holdings, income needs, long-horizon accumulation, concentration breaches, infeasible return goals, contradictory filings, stale market data, incomplete histories, sector comparisons and new market candidates—not only successful trades or popular stocks. Evaluate analytical usefulness and appropriate abstention. If testing realized investment outcomes, use point-in-time data, walk-forward evaluation, corporate-action treatment, costs and controls for survivorship/look-ahead/selection bias. A larger model or additional agents should earn their place through measured improvements.

## Reproduction and setup

No new migration or seed is required for this documentation-only audit. Do not reseed or migrate the live local database to reproduce observations.

For an already installed development environment:

```bash
cd apps/api
source .venv/bin/activate
pytest app/tests/test_phase8_reasoning.py app/tests/test_assistant_orchestrator.py app/tests/test_quant_domain.py -q
```

For a separate clean environment, follow `docs/setup.md`: install `requirements-dev.txt`, configure a local database, run `alembic upgrade head`, and use the existing demo seed only in that isolated environment. Live source ingestion is a separate explicitly operated workflow. Implementation work on execution persistence will likely need a reviewed migration; none is created by this audit.

Selected local references: `docs/architecture.md`, `docs/formulas.md`, `docs/data-sources.md`, `docs/macro-ingestion.md`, `docs/intelligence-v1.md`, `docs/event-intelligence.md`, `docs/PHASE_6_5_DETERMINISTIC_EVENT_IMPACT_PLAN.md`, `apps/api/app/services/context_consumer_service.py`, `apps/api/app/reasoning/peer_groups.py`, `apps/api/app/services/screening_service.py`, `apps/api/app/services/decision_market_inputs.py`, `apps/api/app/tools/registry.py`, and `apps/web/app/assistant/page.tsx`.

Specification reference: [GitHub issue #5](https://github.com/Raahim58/finance_project/issues/5). The proposed read-only analytical tool execution and adaptive-research extension change its current scope; they should be introduced incrementally rather than silently assumed to be part of existing Phase 8.
