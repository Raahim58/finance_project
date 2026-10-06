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

## Oracle live verification — 2026-10-06

Branch `company-evidence`, deployed code `8dc4347` through [run 37400432603](https://github.com/Raahim58/finance_project/actions/runs/37400432603). Canonical migration is `0033_company_digests`; API/web/research worker are running. Ingestion workers/schedulers and the standalone recent-market catchup were paused for deployment/testing; database volumes were preserved. Local port 13000 connects to Oracle through SSH.

Initial public-company tests found complete requests exceeding the unchanged 40,000-byte research input guard. No provider attempt was made for those failures. The model projection now interns document titles/dates, keeps citation locations and exact source-row quotes, leaves full URLs/database provenance in saved snapshots, removes opaque retrieval cursors from model context, and uses existing shared-column encoding for repeated fields. Snapshot version is `company-snapshot.v3`. Offline comparison against the exported public LUCK/FFC snapshots confirmed exact financial values/units/bases/periods, calculated changes and selected news text survived encoding. The focused backend suite passed 64 tests; earlier frontend tests, typecheck and production build passed.

| Live operation | Provider/model | Calls | Provider input tokens | Provider output tokens | Provider latency |
|---|---|---:|---:|---:|---:|
| Saved LUCK brief | Z.ai / glm-4.5-flash | 1 | 10,667 | 1,232 | 36.180 s |
| Saved FFC brief | Z.ai / glm-4.5-flash | 1 | 11,895 | 1,225 | 44.161 s |
| New LUCK chat question | Z.ai / glm-4.5-flash | 1 | 28,874 | 965 | 40.089 s |

Cached input counts reported separately were 280, 287 and 43 respectively; they are not extra input tokens to add to the totals. Reasoning-token counts were not supplied. No Anthropic test was performed in this rollout. No automatic retries or paid fallback were added.

Both briefs were persisted and rendered in Chrome with their original source links. Reopening LUCK returned the same ready job without another brief attempt. The chat question was: “What's the investment case for LUCK, and what could weaken it? Keep it concise.” Execution `eaa628d9-0f5b-45bd-9369-6e0aa94ba81d` completed; first visible answer was 34.229 seconds after acceptance and orchestration took 44.673 seconds. Saved tool trace confirms initial reads of `portfolio.summary`, `ips.compliance`, `research.company_digest`, `market.latest` and `research.search`. Thus chat consumed the saved digest; it did not regenerate a company brief.

**Acceptance is partial, not a financial-quality pass.** The saved/queued/cached path works, but the measured evidence projections still exceed the 3–5K target (LUCK approximately 10.5K locally estimated tokens; FFC approximately 11.8K). Full chat requests also include tool schemas, instructions, separate portfolio/IPS data, citation metadata and extra search evidence. Those costs are not removed merely by caching the company brief. Further compression must preserve material facts/qualifications and be measured again; do not raise limits or label the target achieved.

Confirmed live quality failures remain:

- LUCK's GLM brief described decreasing PKR-per-USD as depreciation, and called an operating-profit growth figure a margin-growth figure. Chat repeated the FX error from the saved brief. Valid source IDs alone did not prevent incorrect interpretation.
- It attributed sales volume/pricing drivers without supplied supporting statements and used historical macro/financial figures without consistently retaining their dates/bases in the narrative. Claims are structurally schema-valid, not semantically certified.
- FFC's stored financial rows still contain earlier extraction/mapping problems. The brief cannot establish trustworthy multi-period growth simply by selecting those rows. All-company fact repair remains separate scope.
- Some chat markers used `[[E25], [E47], [E50]]`, which the existing single-marker resolver does not recognize. Only five citations resolved in that answer. The company panel also repeats equivalent source links and exposes an internal `normalized://` source as a link. These are recorded failures, not fixed by this rollout.

No all-holdings background sweep, Tavily integration, market/news ingestion changes, token-limit changes or duration calculation was implemented here. Macaulay/modified duration is saved as future fixed-income scope in the Phase 11 follow-up roadmap.
