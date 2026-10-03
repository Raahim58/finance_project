# Phase 9–10 research intelligence

## Scope and implementation

Company Intelligence is available for every stored instrument, including companies not held. Portfolio Relevance is a separate projection for one explicitly selected, owned portfolio. Background outputs are qualitative explanations, not investment recommendations or return forecasts. Existing Assistant analysis remains an explicit user action.

| Responsibility | Implementation |
| --- | --- |
| Raw issuer scope, compatible news groups, indirect matching, exact context, portfolio projection | `apps/api/app/services/research_intelligence_service.py` |
| Select two latest reports; retained artifact hash verification; native physical pages and bounded narrative windows | `apps/api/app/services/research_evidence_service.py` |
| Existing-document indexing, citations and embeddings in batches of 128 | `apps/api/app/services/rag_service.py:index_document_pages` |
| Prompt construction, validation, output reuse | `apps/api/app/services/research_generation_service.py` |
| Owner-scoped preview, idempotent enqueue, frozen provider/model, usage | `apps/api/app/services/research_job_service.py` |
| Durable single-concurrency manual worker and recovery | `apps/api/app/jobs/research_worker.py` |
| HTTP routes | `apps/api/app/api/routes/research_intelligence.py` |
| Company-only Assistant scope and shared relevance tool | `services/assistant_execution.py`, `ai/tool_loop.py`, `tools/research_tools.py` |
| UI panels, explicit generation and inline analysis | `apps/web/components/ResearchIntelligence.tsx`, `ResearchBatchControl.tsx`, `ResearchEventCard.tsx` |

Migration `0030_research_intelligence` adds five owner-scoped tables: `company_exposure_profiles`, `company_event_briefs`, `portfolio_event_snapshots`, `research_jobs`, `research_attempts`. Existing document IDs, artifacts, content hashes and extracted financial facts remain intact. Physical document pages gain a unique `(document_id, page_number)` constraint. Migration aborts on duplicate physical pages rather than deleting evidence.

Announcements use raw event IDs and raw issuer links, even when a normalized template cluster combines unrelated companies. Selected/reference/legacy source documents must be public, parsed and observed. Pending/failed references are excluded before pagination. News can share a normalized view only when all cluster members are present and every member has the same raw issuer and explicit factor scope; otherwise views retain raw identity. Stored normalized materiality, classification and freshness remain unchanged.

Read routes never generate, ingest, parse PDFs, register refresh requests or persist context receipts. Missing coverage is displayed. Existing prices, rankings and sector metrics still come from database queries; no market snapshot ingestion is introduced here.

## Evidence and model calls

Report selection is the latest eligible public observed parsed annual report plus latest interim/quarterly report, with publication dates not in the future. Explicit preparation retrieves their retained artifact, checks SHA-256, extracts native physical-page text, and indexes that existing document. No duplicate report is created. Financial extraction queues indexing independently; indexing failure does not undo extracted facts.

Narrative selection uses four SQL-ranked topics (business/risk, oil/energy, debt/rates, imports/exports/currency), at most 32 candidates per topic plus one bounded opening window from each selected report, interleaved into at most 12 distinct physical-page windows of 1,000 characters. Prompt windows collapse PDF whitespace without changing words; physical-page storage preserves the original text. Narrative retrieval does not supply exact numerical facts. Exact fact values use up to 12 stored filing facts, with observed standardized facts filling gaps. Selected macro observations use `BRENT_USD_BBL` (fallback `GLOBAL_CRUDE_OIL_USD_BBL`), `PK_POLICY_RATE`, `PK_USD_PKR`, with future observations excluded.

Only three indirect keys are admitted: `oil_price`, `pk_policy_rate`, `usd_pkr`. Explicit price/rate/currency language is required. An oil discovery is a direct operating event, not automatically an oil-price shock; US policy-rate news alone is not Pakistan monetary policy. Profile relationships require copied source quotes and remain labeled AI-proposed.

The exact system prompts are versioned in:

- `apps/api/app/ai/prompts/company_exposure_profile.md`
- `apps/api/app/ai/prompts/company_event_digest.md`

Each background call has exactly two messages: one system prompt and one JSON user message containing `INPUT_JSON` plus `OUTPUT_SCHEMA`. No tool calls, chat history, continuation, automatic repair or provider retry is used.

| Call | JSON context | Limits |
| --- | --- | --- |
| Exposure profile | Instrument ID/name/symbol/sector; allowed factors; report coverage with actual IDs/hashes; up to 12 narrative windows with physical pages and citation metadata | 32,000 serialized UTF-8 bytes including messages/schema; estimated 8,000 input tokens; 1,500 output tokens |
| Event digest | Company; up to 12 exact stored facts; three available selected macro values; cited AI-proposed relationships; six company narrative windows plus cited relationship windows; up to five events with original dates, metadata, sources and text | 40,000 serialized UTF-8 bytes including messages/schema; estimated 10,000 input tokens; 2,500 output tokens; 160 words/event |

Gemini 3 Flash background calls explicitly use minimal thinking to keep reasoning from consuming the finite JSON output budget; other callers retain existing settings. This setting follows [Google’s thinking API documentation](https://ai.google.dev/gemini-api/docs/generate-content/thinking). Byte limits are enforced; input token figures are estimates, not exact tokenizer guarantees. A batch admits at most eight companies and sixteen calls. Each company needs at most one missing profile call and one missing-event digest call. Reusable outputs cost zero provider calls. Provider/model are frozen at enqueue; preview and reuse for generation respect that configuration. UI polling reports actual provider token usage and incomplete usage explicitly; no unverified dollar price is displayed.

Digest selection takes up to three direct and two supported indirect events, fills vacant slots, then orders materiality/date. The prompt supplies short contiguous source excerpts as quote options; local validation rejects paraphrased quotations. Profile calls use the compact native provider schema. Gemini digest calls use JSON mode plus the full schema in the prompt because the provider rejected the repeated nested claim schema. Full Pydantic limits and citation validation remain mandatory before saving any output. Structured validation rejects unknown IDs, invented or altered source quotes, missing event entries, changed relationship kinds, cross-event source references and overlong output. This verifies structure and source identity; it does not automatically certify semantic causal correctness.

## Worker, cache and failure behavior

Run the dedicated worker explicitly. PostgreSQL advisory lock `903010` limits global concurrency to one; claims also use `FOR UPDATE SKIP LOCKED`. Heartbeat is ten seconds, lease 120 seconds, and provider deadline 60 seconds. Long report preparation runs outside the event loop so heartbeat continues.

A root call reservation is committed before the external request. An attempt records encrypted request, configured model/provider, request hash and status. The key is decrypted server-side immediately before calling the provider, never returned to the client or logged. A response is encrypted and committed before validation and output finalization. Output and stage completion commit together.

- A reserved attempt has not started a request; recovery can send it using the existing reservation.
- A started request without a stored response becomes `uncertain` and is never replayed automatically.
- A stored response is finalized locally after a crash, without another paid request.
- Invalid output is a terminal failure; the worker does not buy an automatic repair.
- Encrypted request/response retention is 14 days; terminal usage/status metadata is retained for 365 days. Cleanup runs when the worker runs.

Reuse is scoped to the same user, company, evidence dependencies, prompt version and model/provider. Company brief prose never becomes canonical source evidence. Portfolio snapshots contain up to 20 deduplicated events; three/five-row UI reads slice a current snapshot. Dependencies include current stored valuation/cash/holdings, event/source/issuer evidence, report context, profile identity, facts, macro observations, saved briefs, calculation version and window date. Invalid snapshots are recomputed in memory on GET; only explicit batch completion persists snapshots. All snapshots and jobs enforce owner scope.

Affected weight is the sum of distinct matched holding market values divided by total portfolio value including cash. Missing prices, incomplete valuation or a nonpositive denominator produce an unavailable weight. Direction, PnL and expected return are not inferred from that weight.

## API and UI

- `GET /research/event-feed`: material event feed, dates/cursor, bounded window.
- `GET /research/companies/{symbol}/intelligence`: five matched events, saved explanations/profile, report coverage.
- `GET /portfolios/{id}/event-intelligence`: selected portfolio events and database-derived affected weights.
- `POST /research/batches/preview`: no writes or provider calls.
- `POST /research/batches`: explicit idempotent enqueue; no synchronous provider call.
- `GET /research/jobs/{id}`: owned status and actual usage.
- `GET /documents/{id}/pages/{page}`: visible physical-page source text.

Research page: company search and selected default portfolio; five market events and five personal events; explicit preview then generate; existing RAG search/library collapsed below. Company page: What changed after price history; expandable exposure relationships and report coverage; separate company analysis and selected-portfolio relevance; Changes/Drivers/Risks/Outlook source purposes; existing chart/workbench retained. Market page: event panel before macro data. Portfolio overview: three events between diagnosis and holdings; research tab: five. Source buttons open a modal physical-page drawer; original links and citation metadata remain visible. Inline analysis reuses the existing Assistant response renderer. Background generation has no automatic page-mount calls; polling runs every two seconds while an owned job is active and stops on scope change/unmount/terminal state.

## Setup, migration and demo preparation

Use the project's configured PostgreSQL, encryption key and artifact store. Existing application setup is in `docs/setup.md`. From the repository root:

```sh
cd apps/api
.venv/bin/alembic upgrade head
.venv/bin/python -m app.jobs.research_batch --user-email YOUR_DEMO_EMAIL --portfolio default --max-calls 16
```

The second command is read-only preview. After reviewing the reported budget, use a stable request ID to enqueue; repeat with the same ID to obtain the same job:

```sh
.venv/bin/python -m app.jobs.research_batch --user-email YOUR_DEMO_EMAIL --portfolio default --max-calls 16 --request-id demo-phase9-10 --enqueue
.venv/bin/python -m app.jobs.research_worker --drain
```

For continuous manual-worker service:

```sh
.venv/bin/python -m app.jobs.research_worker
```

Oracle Compose includes an opt-in research worker. The GitHub deployment workflow starts it with the API and frontend on each push to `main`; the default local Compose stack leaves it opt-in. Paid research generation still requires an explicit batch request. Manual operation:

```sh
docker compose -f compose.oracle.yml exec api alembic upgrade head
docker compose -f compose.oracle.yml --profile research up -d --build research-worker
```

Demo preparation uses the demo user's real stored holdings and public retained evidence. Offline deterministic fixtures live in backend/frontend tests and the Playwright route fixtures; they are never seeded as observed production facts. A larger portfolio must use explicit subsets of at most eight companies via the API. Do not bootstrap an empty local database and present it as the existing observed dataset.

## Verification and remaining scope

Critical tests cover ownership, raw issuer isolation, compatible news merging, narrow factors, physical pages, immutable artifacts/facts, read-only GETs, idempotency, cached reuse, cash weights, strict citations, response recovery and uncertain-call non-replay. Frontend tests cover no paid calls on mount, reviewed preview/enqueue, scope changes and polling. Playwright covers desktop/mobile research, source pages and overflow. PostgreSQL validation runs migration upgrade/downgrade and critical tests in a disposable database, without upgrading the canonical database.

The initial database audit found 14,336 extracted filing facts but no report narrative pages/chunks; 29,091 existing chunks belonged to announcements/news. Extracted report facts already serve exact database queries; this change adds their missing narrative evidence path. The audit also found zero market snapshot rows: these are aggregate index/session summaries, separate from stored company prices, rankings and sector statistics. Snapshot ingestion and stored freshness updates are not changed.

The authorized live-model acceptance run uses retained OGDC annual/interim reports and explicitly dated historical events. Live checks exposed reasoning-token truncation, altered quotes and an unsupported national-to-company FX inference. Minimal thinking, bounded verbatim quote options and a stricter company exposure rule address these findings. The successful two-call OGDC acceptance pair generated two proposed relationships and five cited historical event explanations using 14,459 input and 2,302 output tokens. That is the successful pair’s usage, excluding earlier debugging calls. The canonical database remained read-only, and the temporary evaluation database was removed. The evaluation used real native PDF text and deterministic embeddings for speed; semantic indexing was separately exercised on retained reports. Offline tests are not evidence of live-model quality. Native multi-column PDF extraction can still produce awkward source wording, and one successful issuer evaluation is not a broad quality benchmark. Channel definitions were clarified after review to distinguish asset-value risk from borrowing costs.

Deliberately outside this plan: additional indirect factors such as inflation, full report-corpus backfill/OCR, event impact/PnL/price forecasts, Phase 11 persistent assistant shell and autonomous scheduled generation. Production rollout and demo-account batch generation require running the commands above against the intended deployment; local code and disposable validation do not imply deployment.

Final checks: 114 backend regression tests, 24 frontend tests, four desktop/mobile browser cases, successful production frontend build, and PostgreSQL migration upgrade/downgrade with 23 critical tests, including missing-index evidence admission and numerical grounding checks. Production rollout uses `.github/workflows/deploy-oracle.yml`: push to `main`, build API/web, apply migrations, restart API/web/research-worker and verify readiness. Demo-account batch preparation is a separate explicit action; it is not performed automatically by CI.
