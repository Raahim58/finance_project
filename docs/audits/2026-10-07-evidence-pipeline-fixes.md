# Evidence pipeline investigation and incremental fixes — 7 October 2026

This records code contracts and observations separately. Numerical truth remains in SQL; retrieved text and analyst commentary do not become verified financial values. Ownership checks and encrypted credentials remain required. No model switch, concurrency increase or cohort expansion is part of these fixes. Measured ordinary-question tables and representative execution traces must be added before claiming live acceptance.

## Production precheck

Before further deployment, the read-only precheck found production Git HEAD `39fd904`. The API image identifier began `sha256:9f73…`; running pipeline workers used an identifier beginning `sha256:7ec24…`. These abbreviated identifiers establish image drift, not the complete images' source contents. The pipeline scheduler was stopped with exit code 137; an OOM cause was **not yet verified**. Running workers alone do not establish automatic source cadence or lease recovery.

The corpus precheck counted 199 news documents, including 21 without publication dates. No briefing source target was present. Local adapter code and a setup command therefore do not establish production activation. Verify enabled source/target rows, dispatch-scope compatibility, scheduler ticks, completed stages and original-publisher indexed documents before treating this integration as active. The LUCK/FFC cohort must remain unchanged without authorization.

## Root causes and boundaries

| Boundary | Evidence-backed finding | Fix or remaining boundary |
|---|---|---|
| A. Data | Reported legacy LUCK secondary rows have December fiscal dates despite its June year end. The secondary schema lacks verified fiscal calendar, duration and reporting basis. Some legacy primary extraction admitted narrative figures/percentages. Undated news remains visible as a coverage limitation. | Secondary observations fail closed for exact financial context and calculations; strict extraction is used by the synchronous PSX ingestion path. Existing misparsed primary rows still require a source-by-source review; this is not a claim that all legacy rows were repaired. |
| B. Retrieval | Existing company/sector/broader lanes select five passages initially; research permits ten and two per document. Saved intelligence bypasses these limits. Original briefing discovery repeatedly returned the top bounded URLs, starving lower ranked originals. | The briefing adapter now rotates by original-URL identity within the unchanged allowance. Relevant publisher archives, manual relevance judgment, repeated stories and legacy genre corrections remain quality gates. No new general ranking algorithm or six-excerpt/company cap is claimed. |
| C. Reusable intelligence | Reads previously checked document/fact dependencies but not statement review/correction dependencies. Current prepared sections could be bypassed by a stale saved snapshot. Research editions could coexist and repeat older interpretations. | Actual statement fields and review state now invalidate sections; dependency versions enter section identity. Current source-grounded sections take precedence in pipeline mode. Commentary selects the latest edition per company, sector or overview; older same-day revisions are superseded and earlier dated history survives. |
| D. Payload | Passage limits did not bound dossiers, portfolio/IPS, calculations, history or schemas. Tool component estimates were not the actual request. Conversation summarization was an additional provider request requiring separate accounting. | Company tools accept explicit section selection and disclose omitted/unavailable sections. Wire diagnostics measure actual encoded request bytes/hash and independent component estimates. Summary calls use the execution attempt ledger and budgets. No complete 10K ordinary-request budget has been implemented or validated. |
| E. Model/output | Three completed ordinary answers reportedly had zero resolved citations and no raw citation markers. An answer mixed consolidated profit with standalone EPS. Required Return is a mandate, not a forecast. | A missing/unknown-reference final answer is rejected as synthesis unavailable; rejected prose is not decorated afterward. Financial context preserves period/unit/basis separation. Presence/identity validation does not establish claim entailment or eliminate mixed-basis prose; those remain answer-quality checks. |
| F. Scheduling | Local admission used a two-slot semaphore with a 120-second timeout, permitting accepted work to fail before model access. Discovery committed candidates before fetch successors; a crash could orphan them, and canary scope disables unscoped reconstruction. Arbitrary deadline compensation obscured the wall-time contract. | Admission stays durably queued until capacity/cancellation/recovery. Discovery candidates, live cursor, stage completion and successors now commit together. The running deadline includes credential waits; provider credential timeout remains separate. Existing orphans/dead letters require inspected, bounded recovery. Scheduler restoration requires verified production state. |

## Implemented input/output contracts

| Files | Contract |
|---|---|
| `services/financial_evidence_eligibility.py`; `company_snapshot.py`, `context_builder.py`, `research_service.py`, `research_intelligence_service.py` | Public exact financial reads exclude unavailable/private document evidence and unverified secondary observations. Secondary rows remain stored and separately labelled with missing fiscal-period/unit/basis evidence. |
| `services/ingestion_service.py` | Sourced PSX PDF pages → strict extraction → SQL facts with explicit period start/end, unit and accounting basis; ambiguous text stays unpromoted. |
| `services/pipeline/intelligence.py`; `tools/research_tools.py` | Validated public statements/facts plus dependency versions → selected source-grounded sections or explicit stale/missing states. Section selection is optional and omitted sections remain discoverable. |
| `services/pipeline/briefing.py` | Dated research JSON → immutable artifact and interpretation documents with JSON pointers. Matching same-day revisions are superseded; all distinct sections within the newest edition remain eligible. No financial facts are written. |
| `providers/evidence/briefing_site.py` | `/news.json` original URLs + bounded allowance + persisted URL-hash cursor → rotating publisher candidates. Article publication dates come from the originals, never `/news-meta.json`. Scores/synthesized summaries remain discovery hints. |
| `services/evidence_operations.py`; `jobs/pipeline_tasks.py` | Legacy `discover_stage` defaults to independent commit. Pipeline calls use `commit=False`, flushing candidate/cursor writes until `runs.finish` commits the successor outbox. Failure rolls the uncompleted discovery back. |
| `ai/company_packet.py`; `ai/tool_loop.py` | Explicit selected portfolio → ownership-checked SQL holdings → held-issuer evidence plan; selected portfolio/confirmed IPS remain available to ordinary questions and follow-ups. |
| `ai/source_identity.py`; `ai/token_counting.py`; `services/assistant_diagnostics.py`; `services/assistant_memory.py` | Supplied SQL identity/version/calculation dependencies → stable citation identity. Provider-bound encoded payload → byte count/hash, nonadditive local component estimates, actual reported usage and latency; unknown usage stays explicit. Summaries are recorded provider attempts. |
| `ai/tool_loop.py`; `services/assistant_execution.py` | Final model text + execution evidence map → resolved citations or rejected synthesis. Accepted execution → queued local admission → running claim → wall deadline including credential wait/tools/model. No increase to the two execution slots. |

Paths above are under `apps/api/app/`.

## Evidence-to-provider trace contract

1. Original publisher bytes are retained as a `SourceArtifact` with URL/hash; parsed `Document`, pages, chunks and citations retain source text/date/locators. SQL facts retain exact values, units, periods and basis separately.
2. Retrieval selects ownership-filtered company/sector/broader passages. Public statement dependencies and SQL facts select reusable sections; briefing interpretation keeps its feed provenance and generation time.
3. The selected portfolio resolves through ownership checks. SQL tools calculate holdings/PnL and supply the confirmed IPS, goals, Required Return and available quantitative results.
4. Tool envelopes merge into the evidence packet and execution citation map. Provider projection, history/summary, instructions and native schemas assemble the request. Full evidence remains in encrypted checkpoints.
5. The provider request guard observes the final adapter payload. Exact encoded byte count/hash establishes that boundary; local component token estimates are diagnostic and are **not additive provider usage**.
6. Provider-reported tokens and latency attach to attempts, including summary requests. Raw final text resolves against the execution evidence map before response persistence. Missing or unknown citation references reject the investment conclusion.

This is the implemented path, not a substitute for a representative artifact/record-to-answer trace with actual execution IDs and selected source locations.

## Baselines and validation limits

Keep the reported baselines without presenting them as controlled comparisons: a simple LUCK chat used 28,874 provider input tokens; a coached overview used 11,644 and is not a fair ordinary-user test; an uncoached LUCK/FFC comparison used 59,907 across two provider calls, with company-tool estimates approximately 13,794/14,673. Three ordinary completed answers had no resolved citations. Necessary content must be separated from duplication before imposing limits; exact values, attribution, conflicts and qualifications must survive projection.

**Separate load-test record:** four of seven simultaneously submitted requests timed out in the execution queue. Do not combine this with sequential question results. Removing local admission expiry does not prove successful model access: credential waiting can still time out, or consume the running wall deadline.

Run prompts 1–7 unchanged, then follow-ups 8–10 in the same conversation; keep provider/model and normal selected-portfolio context consistent. Preserve every failure. Before/after live tables, relevance judgments, actual provider usage, first-answer/total latency and citations are pending insertion here. A six-excerpt/company limit and complete 10K ordinary-request budget remain unimplemented/unvalidated proposals.

Focused source/recovery validation passed 68 tests before the commentary revision patch; the source/recovery/revision suite then passed 14 tests. Regressions cover successor rollback/retry, the deployed historical-cursor guard, duplicate artifact pins, rotation, out-of-order commentary, old-artifact replay, distinct sections, retained dates and unchanged original article citations. These are offline checks, not live financial-quality acceptance.

## Setup and migration

No new schema migration or demo financial data is required by these fixes. Existing installations must already have the repository migrations applied. Tests drop their database schema, so use a disposable local database:

```bash
cd apps/api
python -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/alembic upgrade head
DATABASE_URL=sqlite:////tmp/psx-evidence-fixes-tests.sqlite EMBEDDING_BACKEND=hash \
  .venv/bin/pytest app/tests/test_briefing_source.py app/tests/test_briefing_revisions.py \
  app/tests/test_pipeline_discovery_recovery.py app/tests/test_intelligence_dependencies.py \
  app/tests/test_financial_evidence_boundaries.py app/tests/test_evidence_output_contract.py \
  app/tests/test_assistant_memory_usage.py -q
```

`python -m app.jobs.pipeline_status` is the existing read-only operational report. `briefing_source_setup` is a target-creation operation, not a read-only verification command. Do not expand live targets or enable unscoped reconstruction to repair historical gaps without authorization.

Remaining uncertainties include source/archive completeness, audited primary financial parsing, numerical answer entailment, genre repair, relevance/diversity judgment, unknown provider usage, existing canary orphan recovery, production scheduler cause/recovery, and actual unchanged-prompt before/after performance. Pipeline discovery failures preserve stage error/retry records; independent source-health updates in the deferred-commit failure path still require review. Commentary public links remain mutable even though dated source artifacts and pointers are retained internally.

## Completed live suite: deployed first patch

ZAI `glm-4.5-flash`, existing selected portfolio/confirmed IPS, unchanged prompts. Prompts 1–7 used separate conversations; 8–10 continued the comparison conversation. Every outcome is retained. The table reports sums of actual provider-reported input across attempts, including failed executions. Fallback source-panel links are not counted as model citations.

| Prompt | Outcome | Provider input | Calls | Total ms | Raw final markers |
|---|---|---:|---:|---:|---|
| 1. What do you think of my portfolio right now? | synthesis_unavailable (citation_missing) | 16,486 | 1 | 72,805 | False |
| 2. Should I buy more LUCK or FFC? | completed (valid references) | 82,131 | 4 | 109,480 | True |
| 3. Can my portfolio meet my goals? | completed (valid references) | 14,916 | 1 | 45,355 | True |
| 4. What’s happening in the market, and how does it affect me? | completed (valid references) | 16,469 | 1 | 51,889 | True |
| 5. Why has LUCK been moving lately? | failed (tool_call_limit_exhausted) | 87,962 | 5 | 76,918 | False |
| 6. What could go wrong with my investments? | completed (valid references) | 16,146 | 1 | 74,912 | True |
| 7. Are there better options than what I currently hold? | synthesis_unavailable (citation_missing) | 33,263 | 2 | 79,970 | False |
| 8. What about dividends? | failed (tool_call_limit_exhausted) | 77,116 | 5 | 50,973 | False |
| 9. Does that change your view? | synthesis_unavailable (citation_missing) | 67,019 | 3 | 57,631 | False |
| 10. Where did you get that number? | synthesis_unavailable (citation_missing) | 21,749 | 1 | 50,636 | False |

Results: **4/10 completed with model citation markers; 4 citation rejections; 2 tool-call-limit failures.** No unknown input-token usage in these attempts. This patch did not achieve the 10K target. The comparison used 82,131 input tokens across four calls, exceeding the earlier 59,907-token observation. Dynamic market/corpus state was not frozen, so token differences are observed comparisons, not isolated causal estimates.

Manual relevance judgment on the first five passages: portfolio question **2/5 useful or plausibly relevant**, comparison **3/5**. Portfolio selection included generic FFC committee mandates, LUCK promotional prose and Australian domestic budget/inflation context. Comparison included substantive FFC operations and LUCK drivers, Pakistani debt context, a metadata-only transmission notice and the same Australian story. These are small inspected samples, not certified corpus-wide relevance scores.

Live tool trace showed repeated `research.search` failures because `symbols` was a string; the dividend follow-up repeated this shape five times. Company digest prefetch returned missing; stale deterministic sections were not rebuilt by chat reads. The model also continued omitting citations despite available sources.

## Second live-observed increment

The next patch preserves a single string issuer/category filter as a singleton list; excludes inspected metadata-only and generic promotional/governance excerpts unless explicitly requested; requires a global transmission channel for foreign macro context rather than accepting generic inflation/rate words; rebuilds stale public deterministic intelligence from retained evidence without fetching sources or changing ingestion scope; shortens rejected-answer history while retaining source-panel references; permits one no-tool citation repair within existing provider-call/deadline budgets. Regression optimization is deferred per the user’s instruction to test live first. Targeted live results are pending.

## Actual public passage trace

Execution `2b672a01-12e3-4f08-85a2-d85ad922acc6` selected public document `86344785-1d3a-478e-856c-c6b0755ce03a`, artifact `497b3d97-797f-4a1a-8504-cb40d90328cd`, unchanged content hash `add542e86c29e89afd8cc2e568c0e62456c80ae00b036c720593f598c62dd881`. The dated `news` source [Trump Says U.S. Controls Strait of Hormuz as Iran Denies Talks](https://gcaptain.com/trump-says-u-s-controls-strait-of-hormuz-as-iran-denies-talks) supplied chunk `02f7694c-1ad5-4c52-9170-18a58496900d` through the broader lane as `E6`. Its stored passage describes shipping uncertainty; it is context, not proof of company price causation or a verified numerical SQL observation.

Actual attempt `d77f05c3-fe38-4f72-8179-659232b62bd9`: 16486 provider input tokens, 65948 ms, final HTTP-body hash `d861e5308467bed8f04e7721aa20ec32c55c87d7d2f63a3bfb4fc024d2748222`. Retained request reconstructed through the same HTTP JSON encoding matched that hash: **True**. Count-only packet components are retained in the JSON ledger and must not be summed as exact provider usage. The raw answer had no citation markers and was rejected (`citation_missing`), completing a trace of a preserved failure.

## Further live iterations (all outcomes retained)

| Iteration | Prompt | Outcome | Provider input | Calls | Total ms |
|---|---:|---|---:|---:|---:|
| retrieval/cache/scalar fix | 1 | completed (valid references) | 59,207 | 2 | 119,199 |
| retrieval/cache/scalar fix | 2 | completed (valid references) | 70,181 | 2 | 130,978 |
| retrieval/cache/scalar fix | 8 | completed (valid references) | 48,348 | 2 | 75,471 |
| retrieval/cache/scalar fix | 9 | completed (valid references) | 63,112 | 2 | 89,104 |
| retrieval/cache/scalar fix | 10 | completed (valid references) | 62,021 | 2 | 77,115 |
| packet v2 / SQL actions | 2 | completed (valid references) | 34,585 | 1 | 65,349 |
| packet v2 / SQL actions | 8 | synthesis_unavailable (citation_reference_unknown) | 45,326 | 2 | 75,242 |
| packet v2 / SQL actions | 9 | completed (valid references) | 70,871 | 2 | 85,065 |
| packet v2 / SQL actions | 10 | completed (valid references) | 37,253 | 1 | 31,327 |
| historical reference fix | 2 | completed (valid references) | 67,856 | 2 | 115,656 |
| historical reference fix | 8 | completed (valid references) | 23,171 | 1 | 36,301 |
| historical reference fix | 9 | completed (valid references) | 72,275 | 2 | 113,532 |
| historical reference fix | 10 | completed (valid references) | 75,156 | 2 | 79,367 |

The retrieval/cache/scalar increment completed all five targeted questions with references, but remained expensive. Packet v2 completed the comparison in one call (34,585 input); its dividend follow-up was rejected for unknown E130, and that failure is preserved. Historical source titles/URLs remain in model history while old execution-local E labels are removed. The subsequent four-question run completed all four with valid references; input costs still varied greatly with citation repairs. This is identity/presence validation, **not factual entailment certification**. No 10K request budget or six-excerpt/company cap is claimed.

Corporate-action evidence now comes from SQL with unchanged details, original source artifact and explicit effective/ex/payment dates. Percentage of par is not yield; missing cash-per-share or par value stays unknown. The dividend question selects dividend/risk/development sections and retains disclosure of omitted available sections.

Public briefing endpoint live verification: HTTP 200 for news (40 entries), generation metadata and research JSON. Production had **zero briefing targets, candidates or stages** at verification. Adapter deployment is not activation. Its source setup also omitted enabling the research DataSource; the setup code now corrects that and rejects unscoped activation under canary dispatch. Production activation remains separately recorded.

## News-first dispatch correction

User authorized full scope, then prioritized all news/commentary before reports. Older pending report work (9,044 jobs at repair time) was moved to historical mode without deleting job inputs, documents or artifacts. Dedicated pipeline broker deliveries were rebuilt from durable SQL after consumers stopped; unrelated queues were preserved.

Dispatcher gives scoped news/commentary document work and current observations priority over reports. A worker guard defers redelivered report tasks while urgent work is pending, without spending retry attempts. Unstaffed enrichment and historical numerical jobs do not block reports. Live catalog polling selects recent disclosures and at most the newest annual/interim baseline; old PDF children carry explicit historical mode. Existing historical download quotas and byte budgets remain. No migration is required.

Validation: 50 focused tests passed across pipeline restoration, discovery recovery and news-priority tests. Sub-agent critique identified an unscoped blocker and an overly broad urgent definition; both were fixed and regression-tested.
