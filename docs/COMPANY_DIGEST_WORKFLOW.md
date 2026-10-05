# Persistent compact company intelligence

This replaces rebuilding company intelligence in each chat with a saved company-only snapshot and a separately saved cited AI brief. It extends the existing research queue, worker, provider adapters, encrypted attempts and ownership checks. Exposure profiles and individual event explanations remain separate and unchanged.

## Implemented path

1. Opening a company renders `CompanyDigestPanel`. Its authenticated digest read checks stable source fingerprints using database queries only. A current saved result is returned without a model call. No snapshot contains holdings, cash, an IPS or a personal recommendation.
2. Missing/changed inputs enqueue one deduplicated `company_snapshot` job under the existing research batch ledger. Concurrent page opens share its fingerprint/provider/model key. Polls use `active=false`, so they do not enqueue additional work. Explicit Retry is required after failure/uncertain outcomes; ordinary opens never restart the same failed call.
3. The existing `research_worker` builds the snapshot, stores it before generation, then makes one `company_brief` call. That new job does not run report reindexing, exposure-profile generation or per-article AI extraction. Existing worker advisory locking, leases and credential coordination continue to apply.
4. Financial selection keeps latest two annual periods plus latest interim and its matching prior-year interim independently for each reporting basis. Exact values, periods, units and references stay intact. Conflicting sources remain visible and excluded from calculated changes. Missing period starts/bases do not acquire invented growth rates. All omitted historical records remain queryable.
5. Existing bounded company/sector/broader retrieval supplies six passages. Company digests use public company evidence only, excluding private portfolio documents. Excerpts preserve complete sentences and surrounding qualification sentences, including later negative qualifications. An omission flag distinguishes excerpts from complete reports. This cannot guarantee semantic completeness; detail tools remain available.
6. Sources are deduplicated document/page records. Financial and change rows use lossless shared-column encoding in the model request. Price/risk, sector, macro, disclosures and source-backed stored corporate actions accompany the selected facts. Full risk histories, raw reports and duplicate provenance trees are not sent. AI receives exact structured numbers rather than replacing them with its own summary.
7. The JSON brief has thesis, earnings drivers, valuation, catalysts, risks and unresolved questions. Every claim declares reported/management-claim/interpretation and cites supplied IDs. Unknown reference IDs and schema/word-limit failures are rejected without a repair call. Citation validity is not proof of semantic correctness; live quality review remains necessary.
8. The page displays the saved brief, its generation date, source links, missing-evidence notice and refresh status. During failed/pending refresh it retains the last successful brief and resolves its original sources rather than pairing it silently with new facts.
9. Chat's initial company reads use `research.company_digest` and a fresh `market.latest`. Portfolio context remains separately retrieved and ownership checked. Saved digest citations are remapped to execution markers. Older/deeper evidence remains available through existing tools; absent/stale digest evidence is labelled and the model can fetch detail. No token ceilings, provider-call ceilings or tool-call ceilings were raised.

## Size and accuracy verification

The 3–5K target applies to **company evidence JSON**, not the whole provider request or cumulative multi-call usage. Prompts, tool schemas, history, private portfolio data and generated answer tokens are additional. `snapshot.size` records tokenizer-estimated model-projection tokens and bytes. If essential selected evidence exceeds 5K, preserve it and flag `over_target`; do not silently clip facts.

Offline fixtures assert unchanged selected financial values/units/bases/periods/references after compact encoding, correct period selection, excluded conflicting changes, qualification retention, isolated ownership, current-input invalidation, one-call generation/reopen reuse, failed-refresh retention, native citation mapping and UI navigation/poll cleanup. A small fixture is not a measured production-company payload or live-model correctness guarantee.

## Setup and migration

From `apps/api` with the configured application database:

```sh
.venv/bin/alembic upgrade head
# Existing research worker now handles both older research jobs and company digests.
.venv/bin/python -m app.jobs.research_worker
# API startup remains the existing command; embedding preload/deadlines are unchanged.
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Save an active real provider key through the existing settings flow, open a company and wait for the existing worker. No new financial seed data is introduced. Set `ASSISTANT_COMPANY_DIGEST_ENABLED=false` and restart to retain the earlier chat first-pass reads; already accepted executions keep their saved setting. The company digest API still exposes saved results.

Offline verification:

```sh
DATABASE_URL='sqlite+pysqlite:///:memory:' EMBEDDING_BACKEND=hash .venv/bin/python -m pytest app/tests/test_company_digest.py app/tests/test_company_packet.py app/tests/test_research_intelligence.py app/tests/test_phase8_phase2_tool_loop.py app/tests/test_news_retrieval.py app/tests/test_tool_registry.py -q
```

From `apps/web`: `npm run typecheck`, `npm run test -- components/CompanyDigest.test.tsx components/ResearchIntelligence.test.tsx`, `npm run build`.

## Explicit limits

Tavily is not configured in this branch; snapshots explicitly report live web search as unavailable. This change does not invent an integration or ingest external sources. Refresh is triggered by company-page demand after source changes, not a new automatic all-company paid sweep. The existing background queue may wait behind earlier jobs. Apply migration and roll out worker/API/web together before enabling this path in production. No deployment or external model verification is implied by offline tests.
