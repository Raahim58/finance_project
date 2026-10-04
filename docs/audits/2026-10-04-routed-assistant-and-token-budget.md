# Routed Assistant and token-budget audit — 2026-10-04

Scope: compare the user's 18-part hybrid-routing recommendation with the current local checkout, including existing uncommitted changes. This is a code-path audit, not a deployment audit. No live model calls or production database reads were performed. Prior diagnostic usage is historical evidence, not a measurement of today's deployed runtime. No application behavior was changed.

## Conclusion

The structured evidence foundation exists; the proposed routed runtime does not. The active Assistant is a durable, model-directed tool loop. Precomputing company JSON can help reuse and retrieval latency, but reduces input tokens only when runtime selects compact, question-relevant fields. Appending a whole dossier perpetuates the problem.

Keep authoritative numerical records in the database, reusable narrative artifacts with evidence references, and query-specific model packets as separate layers. Reuse existing Canonical Intelligence Context contracts rather than introduce a competing source of truth.

## Comparison with all 18 recommendations

| # | Recommendation | Current status | Work remaining / judgment |
|---|---|---|---|
| 1 | Hybrid routed architecture | Missing in active Assistant | `ai/orchestrator.py` delegates directly to `run_tool_loop`; introduce route → bounded bundle → retrieval → packet → synthesis → checks. |
| 2 | Rules-first, multi-label JSON router | Partial legacy component, inactive in this path | `ai/intent.py` returns the first regex match, and has no production caller found in the checkout. Entity candidates are resolved in `_initial_checkpoint`, but this is not intent routing. Add typed primary/secondary intents, authoritative entities, portfolio scope, constraints, output mode, and freshness needs. Use a small classifier only for ambiguous requests. |
| 3 | Narrow normalized tool registry | Substantially implemented foundation | 23 registered tools, plus conversation-history search. Typed schemas, read-only contracts, ownership-aware portfolio services, and standardized envelopes exist. Many proposed capabilities remain absent or lack Assistant exposure; see inventory below. Filter the model catalog by route. Do not replicate every suggested tool name. |
| 4 | Tool freshness, coverage, confidence | Partial | Envelope includes status, sources, pagination coverage and size estimates. Some payloads include freshness/quality states. Coverage is often returned-count coverage, not required-field completeness. Standardize dataset time, ingestion time, source kind, missing fields, and quality/conflict flags without fabricating numeric confidence. |
| 5 | Intent-to-tool bundles | Missing in active Assistant | `ASSISTANT_SECTION_MAP` exists in a context adapter, but the active loop does not use it to plan retrieval. Implement small static bundles and conditional follow-ups. |
| 6 | Planned parallel execution | Partial | The loop executes a model-issued batch concurrently with a semaphore of four. The model still determines batch contents and whether retrieval is serial across turns. Build the independent first-pass call list on the server. |
| 7 | Router/planner/synthesis/validator prompts | Missing as an active role split | Assistant uses one active `SYSTEM_PROMPT`. Separate exposure/digest prompts belong to background research generation. Files named for other agents do not establish runtime wiring. Start with deterministic planning/fusion/checks, a synthesis prompt, and optional narrow classifier/semantic validator. |
| 8 | Formal portfolio risk chain | Partial, uneven exposure | Holdings/weights, IPS compliance, HHI, covariance risk contributions, historical VaR/ES, drawdown and benchmark calculations exist. Current Assistant does not enforce a complete risk chain. Market liquidity, days-to-exit, systematic factor tilts, active share/hidden overlap, turnover, and standardized top-5/top-10 diagnostics need dedicated contracts/coverage. Existing scenario calculation is not a read-only Assistant stress-test tool. |
| 9 | Results/filing analysis chain | Partial evidence, missing workflow | Financial facts, normalized announcements/events, archived documents and page navigation exist. No mandatory announcement-category analysis chain, dedicated result summary/history bundle, or event-aligned stock-reaction tool was found. Do not infer what was priced in or whether a reaction was justified without supporting expectations/reaction evidence. |
| 10 | Sector-specific analysis templates | Partial classification/comparability, missing full templates | Authoritative PSX sectors and financial comparability machinery exist. No complete active bank/E&P/cement/fertilizer/textile evaluation templates were found. Add only metrics with sourced structured support; explicitly flag absent NIM, production, dispatches, etc. |
| 11 | Dataset freshness and fallback ladder | Partial, meaningful foundation | Trading-calendar/source-SLA price checks, context states, deficiency/refresh infrastructure, and ingestion services exist. Not every tool expresses the same freshness contract. Company facts are marked current when facts exist, which does not prove the latest report has been ingested. No unified runtime fallback ladder or conditional raw-filing extraction bridge was found in the Assistant. |
| 12 | Closed-context retrieval priority | Boundary implemented; ordering missing | Active system prompt prohibits external web and distinguishes database values from document text. Runtime retrieval priority is model-chosen. Preserve the boundary and enforce ordering in the bundle executor. |
| 13 | Evidence fusion | Limited compaction, missing semantic packet | Compact table encoding, exact-result deduplication, repeated RAG chunk suppression, and allocation-result projection exist. They are not a facts/conflicts/gaps fusion layer. `reasoning/projection.py::project` has test references but no production caller found. Create a deterministic query-specific packet. |
| 14 | Explicit answer modes | Missing | Active answer text is flexible prose; no routed quick answer/research note/earnings memo/risk report contract. Add mode-specific evidence requirements and response limits. |
| 15 | Failure-mode prevention | Partial | Tool/provider ceilings, schema validation, source IDs, ownership controls and freshness checks exist. Multi-label routing, semantic claim checks, mandatory liquidity disclosure and enforced portfolio-analysis completeness remain gaps. |
| 16 | Minimal production stack | Existing pieces, not assembled | Reuse registry/data/risk services and durable execution. Add routing, static planning, bounded model packets and enforceable checks first. Defer unsupported news/ownership/backtest capabilities. |
| 17 | Separate responsibilities | Not achieved in active Assistant | The answer model currently owns tool choice, investigation sequencing, interpretation and final prose. Citation resolution does not independently verify its reasoning. |
| 18 | Full reference flow | Not implemented end to end | Adopt incrementally with replay comparison; preserve durable checkpoints, accounting, provider protocol continuity and allocation verification. |

## Existing tool coverage versus proposed inventory

- **Market:** `market.latest`, `market.series`, `market.overview`, `market.freshness`, `market.universe`, `macro.releases`. Latest price and bounded OHLCV are available; default history is 30 observations, capped at 260 per page. No dedicated volume profile, technical levels or relative-performance basket tool.
- **Company:** `research.company_sections` selects exactly one of company facts, market risk, sector, macro or events. Facts are paginated, default 25; builder reads up to 100 filing plus 100 standardized facts before projection. Generic facts/screening context is not a complete standardized statement, valuation, dividend-history or sector-specific metric API.
- **Filings/news:** `research.events`, `research.event_relevance`, `research.search`, `documents.discover/read/navigate/page_images` provide stored event and document access. Dedicated board-calendar, corporate-action history and latest-result analysis tools are absent from the registry, even though ingestion/data services exist for some related domains.
- **Ownership/flows:** no dedicated insider, major-holder-change or block-trade tools in the registry.
- **Screening:** screening snapshots/services exist; `market.universe` provides discovery. No registry-level `run_equity_screen` with the pasted filter/sort contract or screen backtest. Peer evidence can be selected through the sector section, but that is not a dedicated peer-group/valuation interface.
- **Portfolio:** `portfolio.summary`, `portfolio.performance`, `ips.compliance`, `scenario.history`, `quant.portfolio`, `quant.risk_budget`, `allocation.verify`. Summary supplies holdings and weights; performance returns raw points. Exposure/turnover and mandatory market-liquidity reports are not dedicated interfaces.
- **Risk:** `quant.security` and portfolio quant calculations exist. `scenario.history` reads saved runs rather than computing a new read-only stress test. A scenario service elsewhere in the app does not automatically make a capability available to this Assistant.
- **Quality:** `market.freshness` and context states exist. Dataset-specific coverage/last-successful-ingestion are not a uniform Assistant tool contract.

## What is inflating input

1. **Broad catalog each turn.** `_catalog` exposes all registered tools plus history search for ordinary requests. Company-only scope filters by namespace, not question intent. Historical initial calls used about 6,970–7,256 input tokens; this includes system/query/history/catalog, so the CSV does not isolate catalog cost.
2. **Accumulated tool transcript.** The loop appends model tool calls and tool results, and passes accumulated turns into subsequent provider requests. Exact-result deduplication reduces repeated identical results but retains the first complete result. Transport differs by provider: Gemini uses continuation IDs; do not assume identical network replay semantics for every provider.
3. **Raw analytical records.** `quant.portfolio` includes full covariance and correlation matrices and rolling arrays. Matrix payloads grow quadratically with holdings count. Most answers need derived metrics, top contributions and anomalies rather than matrices.
4. **Raw performance points.** `portfolio.performance` defaults to 365 points and permits 5,000. Routine performance questions should receive a computed summary, requested time window and bounded explanatory detail.
5. **Verbose section payloads.** Company sections retain operational/provenance fields and sources. A company-facts request defaults to 25 records regardless of which financial metrics the question needs. Column encoding saves repeated keys, but does not select information.
6. **Large history allowances.** Trial 1 permits a 24,000-token summary threshold and 12,000 recent tokens plus up to 3,000 summary output. Trial 2 is larger. Conversation summarization already exists; missing history summarization is not the central diagnosis. Within-question tool accumulation remains a separate issue.

Historical CSV: `docs/audits/PHASE11_ANTHROPIC_TOKEN_USAGE_2026-10-03.csv` contains five executions with cumulative inputs 35,163; 23,075; 43,688; 39,966; and 54,162. Continuations range from 14,333 to 32,910 tokens. The saved live validation records a simple GLM price lookup consuming 29,849 cumulative input tokens; the tokenizer document identifies 4,283 initially and 25,566 for continuation. These demonstrate prior amplification, not a promised saving or a current per-component attribution.

Token-counting improvements documented in `docs/TOKEN_COUNTING_IMPLEMENTATION.md` are now in the checkout: provider count preflight/local tokenizer support. They improve reservation accuracy; they do not make the transmitted evidence smaller. Raising ceilings has the same limitation.

## Precomputed company JSON: the correct design

Three separate representations:

1. **Authoritative stores:** structured financial facts, prices, filings, events, artifacts and calculations. Exact values remain database-derived. Keep full provenance and archived raw documents.
2. **Reusable company sections:** normalized latest facts, comparable-period trends, sector metrics, evidence-linked exposure narrative, bounded event briefs and coverage. Recompute only invalidated sections. `CompanyExposureProfile`, `CompanyEventBrief`, `CompanyScreeningSnapshot`, stored analysis runs and dependency-checked context caching already provide parts of this architecture. Exposure profiles/event briefs are user/provider/version scoped; do not make them globally shared without revisiting scope and permissions.
3. **Runtime evidence packet:** include only fields required by the route, a small citation map, freshness states, conflicts, missing requirements and safe derived metrics. Attach fresh selected-portfolio holdings/IPS only for portfolio-aware requests. Never persist one user's portfolio inside a global company dossier.

Suggested schemas, not implemented:

```text
company_section:
  schema_version, instrument_id, section, source_dependency_hash
  metric_definition_version, accounting_basis, period, generated_at
  dataset_as_of, last_successful_ingestion_at, freshness_state
  facts[{fact_id, metric, value, unit, period, source_ref}]
  derived_metrics[{method_version, input_fact_ids, value, unit}]
  narrative_claims[{text, evidence_refs, fact_ids, claim_type}]
  missing_fields, conflicts, source_refs

runtime_packet:
  route{primary_intent, secondary_intents, entities, portfolio_id, mode}
  facts, derived_metrics, narrative_claims
  freshness, coverage, conflicts, required_gaps, optional_gaps
  citations{evidence_ref: minimal_source_metadata}
  detail_handles, packet_token_count
```

Use database JSON/JSONB or existing persisted models for materialized sections, not hand-maintained `LUCK.json` files. A timestamp/TTL alone is insufficient: invalidate on relevant filing versions, prices/actions, metric definitions, source corrections and event ingestion. Cross-section calculations must agree on accounting basis and period. A cached section must never turn an unresolved conflict into an accepted fact. Preserve source IDs independently of request-local `E1` markers; assign those when assembling each request.

For “latest LUCK price,” select identity + latest price + date/source/freshness. For “LUCK earnings,” select comparable results + deltas + relevant result-event evidence. For “does LUCK fit this portfolio,” add fresh portfolio/confirmed IPS, material concentration and risk metrics, and relevant company sections. None requires the entire company archive.

## Implementation sequence

### 1. Measure and shrink current model projections

Instrument system/catalog/history/results separately, by tool and section, recording counted tokens, output size, latency and provider usage. Do not log plaintext credentials or publish private portfolio prompts. Build offline replay fixtures from sanitized captures. Preserve dates, units, conflicting facts and citations in every projection.

Project `quant.portfolio` into key risk metrics, sample metadata and top contributors; retain matrices server-side behind detail handles. Add performance summaries instead of default daily-point dumps. Add requested-metric/latest-comparable-period selection for fundamentals and compact citation metadata. Keep full originals for UI/audit and drill-down.

### 2. Rules-first router and static executor

Add typed multi-label routes. Unknown/ambiguous cases get a bounded classifier or safe clarification; retain current fallback initially. Rules do not silently override selected portfolio scope. Expose route-specific tools, with narrowly controlled expansion for legitimate cross-domain questions. Fire independent reads concurrently using separate sessions as the current executor does.

Quick price answers can use deterministic rendering with freshness/citations and zero generation calls. Education needs no company database packet. Research/portfolio routes usually need one synthesis call after server retrieval. Allocation remains conditional and must preserve capacity for exact proposal verification.

### 3. Fusion and bounded evidence packet

Use deterministic selection/deduplication/comparability/conflict detection first. Fetch second-pass evidence only for explicit required gaps or contradictions. Cap calls, entities, rows and total input by mode; if core evidence cannot fit, return a precise incomplete state rather than silently discard it. Do not concatenate old tool dumps into final synthesis.

Initial engineering targets to validate, not locked limits: quick price packet under 1,000 evidence tokens; company research 3,000–6,000; portfolio risk 5,000–8,000; history 1,000–2,000 plus compact conversation state. Total provider input also includes instructions/tool schemas/provider formatting. Broad screening must use compact sector discovery and bounded deep dives; these targets do not justify silently shrinking the eligible universe.

### 4. Materialize missing reusable sections

Extend existing generation/ingestion/context machinery after identifying uncached expensive sections. Deterministically precompute trends and metrics; use background models for narrative extraction only where useful and validate source support. Ingestion dependency changes queue refreshes, and runtime can return an explicitly stale usable snapshot or a gap. Avoid per-company model generation on every price tick.

### 5. Enforce validators and finance completeness

Deterministic gates: known citations, units/period/basis, source freshness, demo flags, required evidence and successful allocation verification for any recommended trades/weights. Semantic citation support is distinct from merely resolving marker IDs. Add a small semantic validator only on recommendations, earnings interpretation and portfolio risk where justified; send the compact packet and draft, not another raw retrieval transcript. Limit corrective cycles.

Portfolio reports must cover concentration, market liquidity, benchmark limitations, downside and IPS fit, or explicitly report those blocks unavailable. Cash needed by the IPS is not market liquidity. Current screening liquidity proxy is normalized share volume, not traded-value capacity or days-to-exit.

Sector templates, event-reaction analysis and additional market-risk tools follow as separate source-backed increments. Ownership flows/backtests are optional capabilities, not prerequisites for token reduction. No schema migration or seed change is required for this audit; persisted section/route contracts in a later implementation must include migrations and demo fixtures.

## Why not implement the pasted plan literally

- A model for router, planner, fusion, synthesis and validator on every request would introduce avoidable calls and latency. Static bundles and deterministic fusion cover most of the initial need.
- Every listed first-pass tool should not fire indiscriminately. Price-history or news retrieval is unnecessary for a latest-price question. Bundle requirements must depend on the actual question and answer mode.
- JSON is an interface, not compression. Smaller selected facts produce savings; moving the same archive into JSON does not.
- Prompt caching may lower effective cost or latency where supported; it does not enforce relevance or reduce the model's logical context. Provider-specific caching is a secondary optimization, after payload reduction.
- Financial conclusions such as “already priced in” require evidence, not a mandatory rhetorical slot filled with a guess.

## Verification

Targeted existing regression suites for registry/read tools, canonical context and research intelligence: **69 passed in 44.49 seconds**. This verifies those existing foundations, not the proposed routing architecture or every finance conclusion.

```sh
DATABASE_URL='sqlite+pysqlite:///:memory:' EMBEDDING_BACKEND=hash \
  apps/api/.venv/bin/python -m pytest \
  apps/api/app/tests/test_tool_registry.py \
  apps/api/app/tests/test_phase8_phase1_read_tools.py \
  apps/api/app/tests/test_phase7a_canonical_context.py \
  apps/api/app/tests/test_research_intelligence.py -q
```

No live model calls, deployment, trades, portfolio changes or issue publication.
