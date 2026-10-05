# Compact company-intelligence workflow

Implemented scope: deterministic first-pass evidence assembly and fusion, followed by the existing answer/tool loop. No new article-extraction, routing, summarization or validation model calls. No ingestion, UI or portfolio changes.

## Execution

1. `ai/tool_loop.py::_initial_checkpoint` snapshots validated company and owned portfolio identities. A typed company/portfolio selection takes precedence over mutable page state; original message contexts remain unchanged. Persist the compact-workflow setting for this execution.
2. `ai/company_packet.py::initial_calls` builds a bounded initial read plan from the actual question and resolved identities. The lightweight text hints only select initial reads; they do not classify normal/deep questions, restrict follow-up tools or decide recommendations. Latest-price questions read only `market.latest`. General company questions read latest price, financial facts, sector, market risk, direct/indirect events and document evidence. Portfolio-related questions add the selected portfolio summary and IPS. Portfolio-only questions also retrieve numerical portfolio analysis and document evidence. No portfolio is guessed from prose.
3. `_prepare_evidence` reserves those reads against the existing 12-call budget. At most eight initial reads leave four calls for follow-ups/verification. Execute independent handlers with four concurrent tasks, each using the existing separate, ownership-checked database session and tool timeout. Save the exact plan before execution. Recovery resumes incomplete reads without reserving them again.
4. Existing `research.company_sections` and `research.search` supply bounded evidence: 20 financial observations, five events, up to five sector peers and five document passages per initial query. Existing company/sector/broader-news retrieval handles deduplication and relevance. Preserve cursors, date scope, coverage and remaining counts. A comparison exceeding the initial allowance explicitly records which companies/sections were visited; the model can retrieve missing sections.
5. `merge_result` assembles one versioned JSON packet: identity, typed tool/section scope, numerical facts, document excerpts, sources, pagination, missing data, conflicting values and financial changes. Source IDs map to execution citation markers. Repeated records and excerpts merge by identity. Failed follow-ups cannot erase previously successful evidence. Duplicate quote text and instrumentation are omitted.
6. `financial_changes` uses Decimal arithmetic only for unconflicted, finite observations with compatible metric, period type, duration, unit, currency and accounting basis. Retain both original periods and citation references. Equal-length, non-overlapping quarters can be compared; partial/full or quarterly/cumulative periods cannot. Unknown basis and unavailable comparable pairs are explicit limitations. Percentage changes are not calculated against zero/negative denominators. Nothing is labelled annualized growth automatically.
7. `project_turns` supplies the packet alongside the original question/history. Native tool-call/result associations, continuation IDs, reasoning blocks and images remain intact. Successful fused tool results become small acknowledgments pointing to the current packet; validation/provider/tool errors remain visible. There is one current packet per outgoing request, not another copy for every earlier tool round.
8. Model-directed tools remain available. Their results merge into the packet. The existing allocation verifier and renderer remain authoritative; no financial checks are relaxed and no trades are executed. Initial portfolio analysis omits covariance/correlation matrices and rolling arrays, while preserving headline metrics, sample, assumptions and warnings. A model-directed `quant.portfolio` read can expand those details. Full originals stay in the encrypted execution checkpoint.
9. Reuse `context_builder`'s company-section cache, partitioned by user/instrument/section and dependency hash. Company keys contain no portfolio ID/context; private portfolio results are assembled afresh into the owned execution. Cache reuse checks authoritative dependencies before returning a deep copy. Financial dependency keys now include metric, period, unit, currency, reporting basis and source metadata so a corrected basis cannot reuse an old fact section. This is a process-local five-minute cache, not durable cross-user memory.
10. Persist a packet receipt containing version, serialized model-packet bytes, initial read count, preparation latency, gaps and conflicts. Existing provider accounting still records actual calls and usage. Offline fixtures compare legacy and compact transports while checking periods, values, citations, gaps, recovery and native protocol. Offline elapsed times are not live-model latency claims.

## Configuration and verification

`ASSISTANT_COMPACT_EVIDENCE_ENABLED=true` is the default. Set it to `false` and restart the API for the legacy comparison path. Already accepted executions keep their saved setting. Token trials, output limits, question limits and provider concurrency are unchanged.

No migration or seed changes are required: packets, original tool envelopes and metadata use existing encrypted execution checkpoints and saved answer metadata. Existing ingestion workers are not started by this feature.

From `apps/api`:

```sh
# Use the project's existing virtual environment; tests remain offline.
DATABASE_URL='sqlite+pysqlite:///:memory:' EMBEDDING_BACKEND=hash .venv/bin/python -m pytest \
  app/tests/test_company_packet.py app/tests/test_phase8_phase2_tool_loop.py \
  app/tests/test_phase11_workspace.py app/tests/test_token_counting.py \
  app/tests/test_phase7a_canonical_context.py app/tests/test_research_intelligence.py \
  app/tests/test_tool_registry.py -q

DATABASE_URL='sqlite+pysqlite:///:memory:' EMBEDDING_BACKEND=hash .venv/bin/python -m pytest \
  app/tests/test_assistant_scope_fixes.py app/tests/test_allocation_targeted_fixes.py \
  app/tests/test_news_retrieval.py app/tests/test_phase7b_context_consumers.py \
  app/tests/test_phase8_phase1_read_tools.py app/tests/test_providers.py \
  app/tests/test_zai_provider.py app/tests/test_llm_provider_usage.py -q

# Normal API startup, using configured database and server-side credentials.
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

## Offline comparison

The same company fixture uses six backend reads in both modes. The legacy mock model first asks for the reads, then answers; the compact path has evidence before its first model call. See `audits/2026-10-04-company-packet-comparison.json`. This verifies orchestration and payload reduction, not real-model financial recall or recommendation quality. Live checks and deployment are separate rollout steps.

The first pass is deliberately bounded, not a complete company archive. Existing missing data and incomplete corporate-action coverage remain visible. Large comparisons, older reports and detailed calculations may need model-directed follow-ups; exhaustion of existing limits still produces the existing incomplete outcome.

## Startup and live verification

`main.py::lifespan` preloads the existing local embedding model in a worker thread before accepting requests. This moves its measured approximately 16-second initialization into startup, rather than the first news tool's unchanged 10-second deadline. A preload failure logs its exception class and leaves normal retrieval availability handling intact. No model, token allowance or tool deadline changes were made.

The model packet exposes `financials`, `market`, `comparisons`, `events`, `portfolio`, `risk_checks`, `additional_evidence`, sources, changes, gaps and conflicts. Internal section storage is not duplicated in the model request. Citation references remain beside individual numerical observations and both periods of a calculated change.

135 targeted tests and 69 regression tests passed. See [live verification](audits/2026-10-05-company-packet-live.md) for measured Anthropic/Z.ai results, cold-start failure and successful startup smoke. Anthropic completed cited company analysis and a verified portfolio proposal; GLM still failed citation/reporting-basis or allocation-verification requirements. Those quality failures remain unresolved and are not treated as budget exhaustion. New code was tested in isolated Oracle containers; it has not been rolled into production by this verification.
