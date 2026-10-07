# Pipeline restoration: implemented contracts and production canary

This document describes the code, rather than an assumed final architecture. Public company intelligence stays separate from a user's selected portfolio and confirmed IPS. Financial values and calculations come from SQL; document retrieval supplies source text. The initial production cohort is LUCK/FFC. Expansion or rollback requires the user's confirmation.

## Data and schemas

Migration `0034_pipeline_restoration` adds the tables below; `0035_pipeline_text_index` adds PostgreSQL weighted text search. IDs are UUID strings; timestamps are UTC; JSON uses JSONB on PostgreSQL. Exact financial values continue to use the existing `FinancialFact` NUMERIC columns. The frozen migration contains the executable column types, foreign keys and indexes. ORM contracts are in `apps/api/app/models/pipeline.py`.

| Table | Contents and constraints |
|---|---|
| `source_targets` | source/config/issuer IDs, adapter, URL, schedule, cursor, enabled; unique source + scope |
| `ingestion_stage_runs` | stage, subject, input hash, code version, live/history/replay mode, bounded input/output JSON, status, attempts, lease/fencing token, heartbeat, next retry, dispatch reservation; unique stage + subject + input hash + version |
| `document_sections` | document, order, kind, heading, unchanged text, physical PDF page or null, start/end offsets, parser version; unique document + parser + order |
| `document_entity_links` | document, instrument, role, matching method, section, supporting quote, validation; unique document + instrument + role |
| `evidence_statements` | source quote, subject, statement kind, event type, lifecycle, topics, sentiment, typed candidate data, attribution, periods/basis, extraction method/version, fingerprint, validation and supersession |
| `statement_evidence` | statement + section, verbatim quote, offsets and locator; composite primary key |
| `event_document_links` | event + document + statement, evidence role; supports several events in one document |
| `company_intelligence_sections` | issuer, section, version, input hash, evidence content, citations, gaps, validation and preparation time; one selected version per issuer/section |
| `intelligence_dependencies` | section version → source/statement/fact version; reverse lookup index |
| `enrichment_attempts` | stage, attempt, requested/actual model, encrypted transport, usage and error code |
| `service_credentials` | application purpose/provider, encrypted key, active flag; no frontend key read |
| `artifact_pins` | artifact + consumer type/ID; protects referenced bytes |
| `document_classifications` (0037) | document, content hash, classifier version, method/model, gaps, validated output; unique document + hash + version |
| `event_cluster_features` (0037) | per event record: entities, canonical reporting period, counterparties, attributed amount claims, direction, evidence embedding |

Existing documents, pages, chunks, citations, financial facts, market observations, macro observations and coverage records retain their identities. `exchange_calendar_days.session_windows` supports Friday's two sessions and exceptional calendars.

## Workers: input → action → write → successor

All Celery messages contain **one stage-run ID**. Arguments and cursors live in SQL. `app/jobs/pipeline_tasks.py` supplies `pipeline.execute`; `services/pipeline/` contains the small processing modules.

| Stage / queue | Input and action | Writes / next stage |
|---|---|---|
| discover / discovery | approved source + cursor; fetch feed/archive metadata | candidates, source health/cursor → fetch IDs |
| fetch / fetch | candidate ID/revision; check budgets, fetch bounded response | immutable artifact/hash, disposable spool → parse |
| parse / parse | raw artifact; HTML main text or PDF text | parsed evidence, source/body dedupe, legacy story link → index |
| index / heavy | accepted parsed evidence | document, pages, lexical chunks/citations and bounded embeddings → sections |
| sections / parse | document ID | unchanged sections and offsets → link |
| link / parse | sections + instrument/name dictionaries | literal issuer/entity links; ambiguous aliases skipped → classify |
| classify / enrich | source sections and stored entities | one validated record per event in the article (model when enabled, rules otherwise); older statements for the document superseded → events (`extract` runs queued earlier take this path) |
| events / enrich | validated fact/report/claim/guidance statements | SQL candidates + embedding similarity + merge blockers; one event record with 1–3 evidence spans, lifecycle history and compatibility records → affected issuer intelligence |
| intelligence / intelligence | issuer + changed input version | eight source-linked sections; unchanged section versions reused |
| enrich / model | explicitly reviewed public nonpersonal sections | free-only strict-schema proposals and encrypted attempt; human review required |
| reports / discovery | issuer | accessible PSX report catalogue → report fetches |
| report_fetch / fetch | catalogue item | raw PDF + document → report_extract |
| report_extract / heavy | document | deterministic numerical extraction/coverage → report_index |
| report_index / heavy | retained PDF | complete lexical text, citations, bounded vectors → sections |
| history_prices / numeric | issuer/year/month | existing observed OHLCV ingestion and coverage |
| prices / numeric | current session, optional cohort | source market-state check, universe metadata and intraday quotes; daily history remains separate |
| secondary_tables / numeric | issuer | SCSTrade raw captures for review; no guessed financial units/basis |
| maintenance / parse | bounded sweep | encrypted transport expiry, uncited terminal raw expiry, old-vector demotion |

New document stages commit their outputs, completion and successor rows together. Legacy adapters retain their existing independent commits; recovery reconstructs their next stage from persisted candidate state. This is a staged integration, not a claim that every legacy transaction was replaced.

Workers use late acknowledgements, prefetch 1, a 300-second hard limit, a 360-second DB lease and a 1,800-second Redis visibility timeout. Fencing rejects stale completion. Failed publication becomes dispatchable after 60 seconds. Dispatch reserves roughly four live slots per historical slot. Retries live in SQL; no long Celery countdowns.

## Scheduling and scope

`pipeline_scheduler.py` owns the 30-second dispatcher. The tick does not poll sources every 30 seconds. PostgreSQL advisory locking allows one scheduler owner.

- News: **10:00, 14:00, 21:00 Asia/Karachi**.
- Announcements/report discovery: **18:00 daily**.
- Quotes: hourly buckets inside regular sessions. Monday–Thursday 09:32–15:30; Friday 09:17–12:00 and 14:32–16:30. Explicit calendars override these windows. Missing holiday calendars are labelled; the source's regular-market state must also be open before quote ingestion.
- Maintenance: 02:00, when its target is enabled.
- Restart: one overdue source bucket plus persisted queue recovery; price polling never catches up overnight.

The production canary uses actual schedulers/workers, with **10 news candidates per news slot, one official report per company per daily slot, and quotes only for LUCK/FFC**. `PIPELINE_DISPATCH_SCOPE=canary` prevents dispatch of unrelated historical or legacy backlog. Targets retain this scope until explicit expansion. The model worker and destructive maintenance are outside the initial canary.

## Source contracts and history

| Source | Implemented use | Limitations |
|---|---|---|
| PSX/DPS | primary reports, announcements, observed universe, monthly OHLCV and session quote snapshots | year-only financial labels never imply December; absent source time is labelled retrieval-time basis |
| Mettis | public listing + `/Home/LoadMore`; title/body article capture | pagination uses **rowid**, not article **newsID**; timezone conflict remains a source uncertainty |
| SCSTrade | existing OHLCV adapter; isolated issuer sessions for IncomeStatement/BalanceSheet/CashFlow captures | secondary tables remain unverified until issuer/units/period/basis checks pass |
| NCCPL | existing authorized/manual CSV flow ingestion | automated access is blocked; no Cloudflare bypass; FIPI/LIPI are flows, not holdings |
| Tavily | bounded approved-domain URL discovery, then ordinary fetch/parse/index | snippets are not facts; no generated answer; application credential needed |

History uses the same ledger and workers as live work. `pipeline_bootstrap --historical-symbol` queues all accessible PSX catalogue items, an 18-calendar-month Mettis traversal, and dated PSX announcements. Price recovery requires a sourced accessible start date through `--price-start`; unavailable start/empty periods remain gaps. Historical completeness is not claimed merely because a job ends.

## Classification and financial checks

Document genre is independent of event type. Official reports/notices remain filings/announcements. Statements distinguish reported fact, management claim, guidance, commentary, background, rumour and interpretation. Lifecycles distinguish proposed, announced, approved, effective, completed, cancelled, updated and unknown. An EOI/due-diligence statement cannot become a completed acquisition.

Topics cover earnings, demand, supply, costs, financing, rates, FX, inflation, trade and geopolitics. Sentiment is a separate subject/aspect/horizon assessment with a supporting quote. Rules leave unassessed sentiment unknown; it never gates positive news admission or becomes a price forecast.

Strict financial extraction requires explicit scale, basis, reporting date and duration. A posting date is not a reporting date. Ambiguous columns remain text. Quarterly/cumulative and consolidated/standalone observations are not combined. Exact values, period bounds and source pages survive projection. Model output cannot write canonical financial facts.

Macro changes preserve their units. A falling PKR-per-USD quote is labelled PKR appreciation, with absolute delta separate from percentage change. Stale macro observations remain visible but are excluded from current regime classification; source URLs are retained.

## Retrieval and provider payload

Retrieval applies public/private ownership, issuer, genre and date filters before ranking. Lexical search includes unembedded history. PostgreSQL uses weighted GIN text search: title A, heading B, body C; expanded terms are OR alternatives. Semantic search uses MiniLM 384-dimensional cosine vectors: exact distance for filtered sets up to 10,000, otherwise HNSW ef_search 100/iterative scan with one ef_search 200 underfill retry.

Initial candidates: 30 lexical + 30 semantic per lane. Lanes are company, sector and broader context. RRF uses k=60. Ranking combines normalized fusion .55, actual lexical coverage .20, scoped relevance .15, source quality .05 and freshness .05, plus the existing content-type adjustment. No generic topic keyword supplies an artificial relevance floor. Broader lanes require Pakistan context or an explicit transmission term. Those rules are provisional relevance gates, not proof of issuer exposure.

Ordinary chat requests five passages by default; research allows up to ten. Exact passage hashes and a two-passages-per-document bound reduce repetition. Empty lanes stay gaps. Company facts/calculations are SQL reads, not values inferred from passages.

Chat initially combines saved company evidence, current market data, fresh stored news and the ownership-checked selected portfolio/IPS when relevant. Missing digests trigger automatic section reads. `tools.catalog` loads additional native tool schemas on demand. Stable source identity preserves execution citations across repeated tools. Provider projection omits repeated quotes/artifact metadata while encrypted checkpoints retain full citations.

Old reference-only AI briefs are not replayed as evidence. Reusable public sections are source-grounded; interpretation/unresolved questions remain explicit gaps pending reviewed synthesis. Ordinary request target is **10K input tokens**, not a claimed measured result. Actual wire requests record count-only component bytes, local count method, provider usage and latency. Component estimates are not added as if they were exact provider token counts.

## Free enrichment and storage

Application-owned OpenRouter enrichment tries `nvidia/nemotron-3-super-120b-a12b:free`, then `liquid/lfm-2.5-2.6b:free`. It verifies the live catalogue's zero prices/schema support, explicitly sets the model and zero prompt/completion price ceilings, and has no paid fallback. Input is bounded reviewed public nonpersonal text; output uses a strict schema, verbatim quote checks and a review queue. Provider quotas can defer work; there is no application daily model-call cap. A catalogue listing does not establish extraction quality.

Capacity defaults: 300 live news bodies/day, 100 historical news bodies/day, 25 historical PDFs/day, 256 MiB live and 768 MiB historical response bytes/day, 200K hot vectors, embedding batches of 32. Per response: articles 5 MiB, PDFs 25 MiB. Raw HTML/JSON uses lossless gzip when smaller, retaining original/stored hashes and sizes.

Raw budget 48 GiB; DB budget 24 GiB; minimum data-volume free space 20 GiB. At 80% alert; at 90% historical work defers; hard pressure defers live bodies. Source work is deferred, not misclassified as irrelevant. Terminal unpromoted raw expires after 30 days only without other FK consumers/pins. Encrypted model transport expires after 14 days. Old unpinned vectors can be demoted without losing text or citations. Accepted/cited document bytes are conservatively retained in this release; aggressive 18-month accepted-news deletion requires a complete legacy citation-pin audit.

## Commands and rollout

Local setup/migration:

```bash
cd apps/api
python -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/alembic upgrade head
```

Production operations (after deploying the exact commit and backing up PostgreSQL):

```bash
docker compose -f compose.oracle.yml run --rm -T api alembic upgrade head
docker compose -f compose.oracle.yml exec -T api python -m app.jobs.pipeline_canary --symbols LUCK FFC --news-limit 10 --report-limit 1
./ops/ingestion start pipeline
docker compose -f compose.oracle.yml exec -T pipeline-parse python -m app.jobs.pipeline_status
```

Full-scope targets/history are separate explicit operations:

```bash
python -m app.jobs.pipeline_bootstrap --approved-sources psx_announcements,mettis,dawn,business_recorder
python -m app.jobs.pipeline_bootstrap --replay-limit 100
python -m app.jobs.pipeline_bootstrap --historical-symbol LUCK --price-start YYYY-MM-DD
python -m app.jobs.pipeline_review --credential pipeline_enrichment
python -m app.jobs.pipeline_review --credential tavily_discovery
python -m app.jobs.pipeline_review --accept STATEMENT_ID
```

Credential input is hidden; keys are encrypted and never returned. `--activate` enables reviewed full-scope targets; removing the canary dispatch restriction is an explicit scaling decision. Do not run legacy ingestion producers alongside the pipeline scheduler. The deployment guard includes pipeline services; a subsequent deployment requires a controlled worker pause.

## Validation and remaining gates

Unit coverage includes lease recovery/fencing, failed publication, full document replay, exact financial period/scale/basis, source correction, citation identity, ownership, unembedded retrieval, schedules/holidays, free-routing checks and isolated SCSTrade sessions. PostgreSQL integration checks the new ledger and text-index/title-change triggers in a disposable schema. Production validation must record actual source funnel counts, artifact → selected quote → provider request trace, repeated-section reuse, citations, tokens, latency and errors.

Remaining quality gates: real free-model extraction accuracy; a manually judged retrieval question set; OCR batching on large scanned reports; exhaustive historical source coverage; complete legacy pin audit before accepted-news deletion; confirmed price-history boundaries; rights/availability for each enabled provider. This implementation must not be presented as having passed those gates without measurements.

## Added public briefing feed

The user-approved site exposes `/news.json`, `/news-meta.json`, and `/research.json`. `briefing_news` discovers each entry's original `urls`; article fetches retain the actual publisher, canonical article URL, body and publication date. The site's synthesized headlines/scores are discovery hints, not verified article facts or market-impact measures. Cross-source URL dedupe preserves the original publisher's stored metadata.

The `briefing` stage captures the research JSON, then indexes its overview, sector highlights and registered stock commentary as `commentary`, with physical pages null and numerical promotion prohibited. Its dated analysis is available through `research.morning_brief` and company digest extra-analysis fields. News citations link to the original articles; research commentary links transparently to its research JSON under the label "Market research commentary". The research feed's embedded FIPI/LIPI or market values do not become canonical database observations.

`python -m app.jobs.briefing_source_setup` creates two source targets, preserving the existing canary batch: six original news URLs per scheduled news slot, and commentary discovery at 09:00 Pakistan time. Existing source/body budgets still apply. No paid model or application enrichment credential is required for capture.

## Event classification and event records (0037)

Questions are answered from saved event records, not by matching question phrases at read time.

**Classify once per article body.** `services/pipeline/classification.py` returns, per distinct event: entities, event type, statement kind, lifecycle, direction, event date, reporting period, counterparties, amount claims, topics, sentiment (subject, aspect, horizon, supporting quote) and one to three verbatim evidence spans. Sectors come from the stored `Instrument.sector` (PSX classification), never from the model.

- *Model path* — only when `PIPELINE_CLASSIFICATION_MODEL_ENABLED=true` **and** an active `pipeline_enrichment` OpenRouter credential exists (`python -m app.jobs.pipeline_review --credential pipeline_enrichment`). Enabling the flag is the operator's attestation that public news/announcement text may be sent to the free provider. The same free-only, zero-price, strict-schema checks as `enrich` apply; requests/responses are stored encrypted in `enrichment_attempts`. Documents needing more than four ~2,800-token batches use rules.
- *Rules fallback* — same contract, used when the flag is off, the credential is missing, the provider returns 429/503, or output fails validation. It groups sentences by entity/type/period per article. It is phrase-based, so its confidence is lower (0.45 vs 0.65) and model output always outranks it.

**Validation before saving.** Evidence quotes must occur in a section of the document, or the event is dropped. Entities must resolve to a stored instrument named in the document (symbol, name or current alias); otherwise the event becomes market-level. Dates need the month and day (or a numeric form) inside the supporting quote. Periods must canonicalise (e.g. `1QFY26` = `first quarter of FY2026` = `Q1-FY2026`) and appear in their quote. Amount digits must appear in their quote. Counterparties must appear in the document, and sentiment needs its quote and a resolved subject. Anything unsupported becomes unknown. Publisher text cannot be a `reported_fact` (it becomes `secondary_report`), and a quoted proposal cannot be promoted to approved/completed. Amounts are stored as `attributed_claim`, never as `FinancialFact` rows.

**Clustering.** `services/pipeline/events.py` takes SQL candidates that share an entity and event type and fall in a compatible window: ±10 days, or ±60 days with a matching or unknown reporting period. It then compares evidence text with the configured embeddings (MiniLM in production); cosine ≥ 0.72 is required. Similarity alone never merges: different reporting periods, opposite directions, disjoint counterparties, or the same amount unit with no shared value all block a merge. The same article never merges with itself; the classifier already separated its events. A proposal followed by an approval or completion is one event: `lifecycle_history` keeps each state with its document, and `lifecycle` is the latest known state.

**Event record.** `NormalizedEvent` (`detection_version='pipeline-v2'`) holds a sourced title (the primary quote), event date (`date_basis` says whether it is a quoted event date or the publication date), current lifecycle, classification, sentiment, confidence, materiality and up to three evidence spans from distinct documents. `EventDocumentLink` lists every member article/statement. Raw `events` rows remain for compatibility, and every original document and citation stays behind the record.

**Reads.** `services/pipeline/event_reads.event_records` filters by entity, type and date in SQL, then ranks by `0.45·freshness + 0.35·materiality + 0.20·confidence`, with freshness recomputed at read time. Company pages, the Assistant `research.events` / company tools (optional `event_types` filter) and portfolio intelligence all read through `research_intelligence_service`. Portfolio intelligence joins records to owned holdings and their stored weights. Legacy rows already inside a record are deduplicated. Document search stays available for deeper evidence.

**Backfill of the existing corpus.**

```bash
cd apps/api
alembic upgrade head                                     # adds 0037
python -m app.jobs.classify_backfill --dry-run           # count pending documents
python -m app.jobs.classify_backfill --limit 500         # queue historical-mode runs
python -m app.jobs.classify_backfill --since 2026-01-01 --document-type news
```

A document is skipped once a classification exists for its current content hash and the target version (model output satisfies a rules target). Rules-classified documents are re-queued after the model is enabled. Unparsed documents run the full chain from `sections`. Stage-run input hashes include the content hash and classifier version, so re-running the job does not duplicate work.

