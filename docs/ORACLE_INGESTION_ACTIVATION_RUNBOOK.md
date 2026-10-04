# Oracle ingestion: exact rollout order

Prepared October 4, 2026. This is an execution runbook, not an activation record. Commands below that start services or publish tasks have not been run. Prerequisite changes are explicitly distinguished from commands supported today.

## Implementation target: relevant geopolitical/economic coverage, not more filing volume

The primary missing capability is a trusted non-PSX current-and-historical evidence lane. Worker activation comes after its admission, archive and storage contracts work. The old financial reindex backlog remains user-owned; new reports still need reliable save/index behavior.

Verified bottlenecks and their corresponding implementation work:

| Bottleneck | Concrete change | Acceptance evidence |
| --- | --- | --- |
| No working dated geopolitical backfill; `news_90d` only targets throttled GDELT | Add one verified authorized dated archive adapter, then weekly durable units in `evidence_history_service.py`; use explicit August 1/start and fixed catch-up cutoff | Relevant August articles with real publication dates, source URLs/text, resume cursor and indexed citations; honest inaccessible-week states |
| Useful geopolitical headlines rejected before their bodies are read | Add curated metadata admission cases and market-channel tags in `evidence_pipeline.py`; keep a bounded fetch allowance for materially relevant but sparse headlines | Positive sanctions/shipping/trade cases admitted; sport, housekeeping, unrelated politics and substring matches rejected |
| Broad flags enable broken/irrelevant sources; queued work can bypass operator selection | Enforce explicit allowlist in source synchronization and discovery/fetch entry points | Implemented locally: excluded discoveries and queued fetches perform no network calls; empty selection stops all; dormant sources stay dormant |
| A source name/HTTP 200 is mistaken for usable evidence | Validate date, article/PDF content, headline/body association and preview status before selection; classify commentary separately | Fixtures for readable dated articles, official short releases, subscription previews, navigation and missing/conflicting dates |
| Canary limits do not cap every ingestion lane or total retained corpus | Add locked byte reservations shared by current/history news, response-size limits and storage-headroom checks before new work | Concurrent jobs cannot each spend the same remaining allowance; history yields to current; hitting limits pauses imports visibly |
| No autonomous Oracle ingestion survives the ordinary deployment cycle | Update Compose/ops/deploy lifecycle only after bounded end-to-end tests | Producers resume after consumers; no abandoned work after restart; current publication reaches retrieval on schedule |

Relevance requirements:

- Admission must identify a supported channel: Pakistan FX/fiscal/monetary conditions; energy supply or import costs; shipping/freight/trade routes; sanctions/export restrictions affecting trade; sourced sector input/demand changes. Preserve separately labeled market/sector evidence; do not manufacture company exposure.
- A publisher's prestige, a geopolitical country name, the word “war”, or a Pakistan tag alone is not sufficient for retained full-text selection. Use headlines/summaries for cheap bounded discovery, then confirm the channel in the article. Political reporting may establish a material policy/security event, but generic political commentary must not fill the corpus.
- Deduplicate exact content/URLs and cluster syndicated stories; retain a material new development or independent corroboration with provenance. Article text remains cited evidence, not a license to infer exact economic measurements.
- Distinguish reported events, allegations, statements and commentary. Broad geopolitical coverage must include material events even when no individual company is linked.

Initial proposed limits for the **new non-PSX evidence lane**, to implement and measure rather than claim as current behavior: 100 fetches/day, 25 selections/day, 256 MiB fetched raw bytes/day combined across current/history, and an 8 GiB retained raw-news ceiling. Reserve at least 75% of daily fetch/selection capacity for current work. Also stop admitting new imports before `/srv/psx` drops below 20 GiB free or root below 8 GiB free. These are starting operational choices, adjustable from measured coverage and growth; the raw ceiling alone does not bound PostgreSQL/vector/index size. Track those physical sizes, spool, Redis and logs separately, with one overall deployment headroom stop. Include other lanes in the overall stop even though they have separate per-lane budgets.

At the corpus ceiling, halt historical admission first and report the capacity state. Relevance filtering cannot guarantee indefinite growth fits a fixed disk. Do not delete retained cited articles/financial PDFs to avoid the halt. Later retention work can rank obsolete unreferenced evidence, protect citation/repair dependencies and then retire it under a documented policy. Existing rejected/temporary spool cleanup can continue under its existing rules.

Implement in this order: (1) explicit source controls; (2) bounded geopolitical relevance and trustworthy article validation; (3) verified dated archive plus resumable weekly backfill; (4) shared current/history byte/headroom controls; (5) new-document reliable save/index; (6) Oracle consumers, current canary, recurring producers; (7) tightly budgeted August recovery. Current-source contract testing can run during archive development; historical fetching starts only when its dates/budgets/cursors are verified. Price/macro structured refresh is a parallel lane, not a substitute for political/economic narrative coverage.

## Verified deployment snapshot

Oracle commit: `38ecd82391ac232b4cb4c65cecf65cc270544eb3`. Running: API, web, research-worker, PostgreSQL, Redis and MinIO; ingestion workers/schedulers are off. Installed extractor: `financial-layout-v4-validated-columns`. Existing chunks all use `sentence-transformers/all-MiniLM-L6-v2`, embedding index version 2.

Of 1,391 financial reports, only **16 have chunks**. Extraction labels: 1,290 parsed v3, 60 parsed v2, 27 needs-OCR v3, 12 needs-OCR v2, two downloaded. An extraction label is not proof of whether a reviewed repair was applied: the targeted repair service does not update that label. Check its fact audit metadata independently. Most historical facts have not been audited with the new parser.

Do not run `reindex_rag` to solve this backlog: it re-embeds existing chunks, materializes all chunks and commits at the end. It neither creates missing report chunks nor repairs numerical facts.

## 1. Finish the new-document path before enabling automatic producers

Make this a small release, with the following acceptance tests. These changes are not implemented by this runbook.

1. In `jobs/phase2_tasks.py`, set the report's company association on download, validate retained bytes against their SHA-256 before extraction, and persist the extracted fiscal period/basis/unit/page exactly. Extend `providers/fundamentals/extraction.py` and the save path to retain a source-observed `period_start` where available; leave it missing where ambiguous. Currently automatic saves omit period start, and the existence check does not distinguish duration/unit. Do not assume the reviewed LUCK manifest's richer metadata is automatically generated for all new reports.
2. Persist extraction output and its completion state in one transaction. Save a durable `financial_index` work item in the same transaction, using the existing `IngestionCoverage` ledger. Publish after commit; have `phase2_orchestration.py` republish missing/failed/expired index work. Current code commits facts and then attempts a Celery publish; a publish failure can leave a parsed report permanently unindexed.
3. In `research_evidence_service.py`, index the same retained native/OCR pages used for extraction. Current `prepare_report()` independently uses native text, so OCR-successful reports can fail narrative indexing. Keep native page numbers, observed metadata, source URLs and matching embedding versions.
4. Make extraction/index work track its own parser/index version and bounded retry state. Do not silently re-extract an existing report with usable old facts: the current existence guard skips matching old facts rather than replacing incorrect amounts. Historical replacement belongs to reviewed manifests that preserve originals with confidence zero.
5. Test one native report, one scanned report, unknown scale, percent/change columns, fiscal dates, standalone/consolidated tables, same-end different-duration columns, repeated task delivery, missing artifact and a broker failure after facts commit. Assert stored values and dates against source fixtures, then assert pages/chunks/citations and `index_current()` success. Keep ambiguous facts unavailable.

Run the existing regression suites, plus the new tests, before deployment:

```sh
cd apps/api
DATABASE_URL='sqlite+pysqlite:///:memory:' EMBEDDING_BACKEND=hash .venv/bin/python -m pytest \
  app/tests/test_financial_fact_quality.py app/tests/test_fundamentals_extraction.py \
  app/tests/test_phase2_ingestion_plane.py app/tests/test_research_intelligence.py -q
```

Use PostgreSQL integration checks for concurrent insert/retry changes; SQLite alone does not exercise the recorded Oracle constraint failures. Keep production embeddings semantic; hash embeddings above are only for isolated tests.

## 2. Prepare source selection and Oracle persistence in that release

1. Repair `/symbols` discovery in `market_providers.py` against an observed working contract; fixture-test it from Oracle. Do not enable current-price refresh while the last verified endpoint returns 404. Reconcile the directory against eligible securities and retain sourced listing/alias history.
2. `EVIDENCE_SOURCE_ALLOWLIST` is now implemented locally in `core/config.py`, catalog synchronization and discovery/fetch entry points; it is not deployed. It uses catalog enablement AND allowlist membership. Explicitly empty allows nothing; unknown keys fail before configuration writes. Unset retains legacy behavior for compatibility, so Oracle must always set an explicit selection. Manual database disables alone are insufficient because catalog synchronization overwrites `DataSource.enabled`.
3. First allowlist: `psx_announcements,dawn,business_recorder,bbc_world,guardian_world,gcaptain,freightwaves,federal_reserve,ecb_releases,bis_releases,eia_releases,cotton_grower,coal_age,metalminer`. Preserve source polling intervals. Exclude known blocked sources and conditional Mettis/Al Jazeera/official Pakistan adapters until their date/discovery/relevance fixes pass the verification report's fixtures. Add each repaired source individually, with a fresh smoke and acceptance check.
4. Fix geopolitical metadata-gate false negatives using sampled positive/negative headlines; use token/phrase boundaries for exposure terms. Do not globally lower thresholds. Fix smoke HTML/PDF routing before using smoke success as an activation gate.
5. Add a **new** `app.jobs.market_price_scheduler` module that runs only `run_market_data_cycle(db, settings.market_data_mode)` on the 300-second schedule, with one active run and bounded failure handling. Move daily screening/ledger/monitoring and legacy SCSTrade/research jobs into their own bounded owner. Do not put the existing mixed `scheduler.py` loop into production and assume it stays on time.
6. Add a **new** `market-scheduler` service to `compose.oracle.yml`, sharing the API image/env, PostgreSQL dependency and command `python -m app.jobs.market_price_scheduler`. Give intended continuous workers/schedulers `restart: unless-stopped`; cap their logs. Add it to `ops/ingestion` start/stop/status and deployment pause/resume lists.
7. Replace the evidence named-volume mount with `${PSX_DATA_ROOT:-/srv/psx}/evidence-spool:/data/evidence-spool` on all evidence workers and evidence-scheduler. Create the host directory with the actual container UID/GID. If the old volume contains pending spool files, preserve/migrate them while producers and consumers are stopped; never empty it blindly. Keep retained artifacts in MinIO.
8. Fix history/sector-stat concurrent upserts before resuming failed history tasks. Add bounded partial-result refresh in `coverage_service.py`; distinguish legitimate no-data from parser failure. Add a separately bounded historical producer so monthly backlog does not compete with current filings in the same refill budget.

## 3. Back up and deploy the release with ingestion paused

Connect from the Mac, then run subsequent commands on Oracle:

```sh
ssh -i ~/.ssh/oracle_psx ubuntu@141.145.146.120
cd /home/ubuntu/finance_project
```

If ingestion is running, record its intended services, stop the producers first, let consumers finish outstanding work, then stop consumers. Today all ingestion services are already off. For later deployments:

```sh
docker compose -f compose.oracle.yml --profile ingestion --profile scheduling ps --services --status running
docker compose -f compose.oracle.yml stop phase2-scheduler macro-scheduler evidence-scheduler
# Include market-scheduler once that new service exists.
docker compose -f compose.oracle.yml exec -T api celery -A app.celery_app inspect active
docker compose -f compose.oracle.yml exec -T redis redis-cli LLEN financial_extract
docker compose -f compose.oracle.yml exec -T redis redis-cli LLEN evidence_index
```

Check every active queue and Celery active/reserved task, not only the two example queues. Preserve durable work if a source failure prevents draining; do not purge Redis or globally reset ledger states. Then run `./ops/ingestion stop all`, including the new market service after its script update.

```sh
run_dir="/srv/psx/backups/ingestion-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$run_dir"
docker compose -f compose.oracle.yml exec -T postgres sh -c \
  'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$run_dir/database.dump"
test -s "$run_dir/database.dump"
docker compose -f compose.oracle.yml exec -T postgres pg_restore --list < "$run_dir/database.dump" > "$run_dir/database.contents"
```

Retain a corresponding artifact recovery point; database rows alone cannot restore missing PDF objects. Verify restore into a disposable database before applying historical fact repairs.

Merge/push the tested release through the project's usual workflow. The existing `Deploy to Oracle` workflow fetches the exact triggering SHA, builds API/web, runs `alembic upgrade head`, restarts API/web/research-worker and checks readiness. It currently refuses deployment with ingestion running and does not restart ingestion afterward. Until lifecycle automation is implemented, use this pause/deploy/manual-resume sequence for every release. Do not run a separate hard reset over unreviewed remote changes.

After the workflow succeeds:

```sh
git rev-parse HEAD
curl --fail http://127.0.0.1:3000/api/ready
docker compose -f compose.oracle.yml exec -T api alembic current
```

Compare HEAD with the workflow's successful deployment SHA. Required migration command, if running the same deployment manually: `docker compose -f compose.oracle.yml run --rm -T --interactive=false api alembic upgrade head`.

## 4. Set consistent configuration; start consumers before producers

Edit `.env.oracle` on Oracle using an editor. Preserve credentials. Set these existing settings:

```dotenv
MARKET_DATA_MODE=dps
MARKET_DATA_REFRESH_SECONDS=300
MARKET_HISTORY_BOOTSTRAP_ENABLED=false
SCHEDULED_RESEARCH_ENABLED=false
MACRO_INGESTION_ENABLED=true
EVIDENCE_ENABLED=true
EVIDENCE_PASS4_OFFICIAL_ENABLED=true
EVIDENCE_PASS4_BREADTH_ENABLED=true
EVIDENCE_PSX_ANNOUNCEMENT_HISTORY_ENABLED=false
PHASE2_BROAD_QUEUE_TARGET=5
PHASE2_HISTORY_QUEUE_TARGET=1
PHASE2_DOWNLOAD_QUEUE_TARGET=2
PHASE2_EXTRACT_QUEUE_TARGET=2
MACRO_QUEUE_TARGET=2
EVIDENCE_DISCOVERY_QUEUE_TARGET=5
EVIDENCE_FETCH_QUEUE_TARGET=10
EVIDENCE_PARSE_QUEUE_TARGET=10
EVIDENCE_INDEX_QUEUE_TARGET=5
EVIDENCE_HISTORICAL_QUEUE_TARGET=1
```

Also set the **newly implemented** `EVIDENCE_SOURCE_ALLOWLIST` to step 2's explicit keys. Do not enable those two broad group flags until allowlist enforcement is deployed. These are initial canary sizes, not existing observed production limits. Small targets bound published queues; they do not replace per-source fetch/byte budgets.

Recreate API/research-worker so their source registry/settings match the consumers. Then start consumers; keep continuous producers off:

```sh
docker compose -f compose.oracle.yml --profile research up -d --force-recreate api research-worker
./ops/ingestion start phase2
./ops/ingestion start macro
docker compose -f compose.oracle.yml --profile ingestion up -d \
  worker-evidence-discovery worker-evidence-fetch worker-evidence-parse \
  worker-evidence-pdf worker-evidence-index
```

For the first canary, lower history/download/fetch worker concurrency to 1 in the release's Compose configuration, keeping PDF/extraction/index workers at 1. Keep `worker-historical-hydrate` off until current work is healthy. Avoid CPU-heavy report backlog and embeddings running simultaneously at full concurrency.

## 5. Prove one new filing end-to-end; then current prices, macro and news

With workers running, publish one bounded Phase 2 refill using an existing function. This does not start a permanent producer or queue monthly history:

```sh
docker compose -f compose.oracle.yml exec -T api python - <<'PY'
from app.db.session import SessionLocal
from app.services.phase2_orchestration import enqueue_reconstructable_phase2_work
with SessionLocal() as db:
    print(enqueue_reconstructable_phase2_work(db, queue_limits={
        'broad_fundamentals': 5, 'dps_history': 0,
        'financial_download': 1, 'financial_extract': 2,
    }))
PY
```

Select the resulting newly downloaded report explicitly. Verify its object hash, v4 extraction, exact saved facts/scale/period/basis against the PDF, retained pages/chunks/citations and `index_current()`. Verify duplicate delivery changes no facts or chunks unexpectedly. If the refill only dispatches catalogs or encounters an old backlog item, repeat bounded refills until one *new* report traverses the entire path; a producer message alone is not success.

Once step 2's price-only module exists and its source smoke passes:

```sh
# New module; supported only after the prerequisite release.
docker compose -f compose.oracle.yml exec -T api python -m app.jobs.market_price_scheduler --once
```

Implement that module's `--once` option along with its loop. Verify nonzero accepted/attempted counts, source trade date, quality rejections and canonical API prices. Label these daily observations; intraday quotes and exchange indices need separately verified adapters/schema.

Publish current macro and evidence once using existing commands:

```sh
docker compose -f compose.oracle.yml exec -T api python -m app.jobs.macro_scheduler --once
docker compose -f compose.oracle.yml exec -T api python -m app.jobs.evidence_scheduler --once
```

Verify macro observation effective/release/retrieval dates in structured tables. Verify at least one newly published Pakistan article, geopolitical article and shipping/sector article reaches selected evidence, indexed text and retrieval with its original dated citation. Official-release narratives do not automatically become exact numerical facts.

Then start continuous producers:

```sh
docker compose -f compose.oracle.yml --profile scheduling up -d macro-scheduler evidence-scheduler
# New service, after step 2 implementation:
docker compose -f compose.oracle.yml --profile scheduling up -d market-scheduler
```

Start `phase2-scheduler` only after its release separates current filing work from bulky historical refill. Preserve its 6-hour incremental catalog cadence and the documented monthly broad-fundamentals refresh. Do not assume today's mixed producer is a dedicated new-filing scheduler.

## 6. Finish missing report indexing separately, in small batches

After current ingestion is healthy, use the existing report index task for explicitly reviewed native-text reports. This command selects up to five currently parsed, public, observed, published reports missing a current index, and publishes only narrative indexing tasks. It does not re-extract facts:

```sh
docker compose -f compose.oracle.yml exec -T api python - <<'PY'
from datetime import date
from sqlalchemy import select
from app.db.session import SessionLocal
from app.jobs.phase2_tasks import financial_index
from app.models.document import Document
from app.services.research_evidence_service import REPORT_TYPES, index_current
with SessionLocal() as db:
    candidates = db.scalars(select(Document).where(
        Document.document_type.in_(REPORT_TYPES), Document.status == 'parsed',
        Document.visibility == 'public', Document.data_status == 'observed',
        Document.published_date <= date.today(),
    ).order_by(Document.published_date.desc(), Document.id).limit(50)).all()
    selected = [d.id for d in candidates if not index_current(db, d.id)][:5]
for document_id in selected:
    financial_index.apply_async(args=[document_id], queue='financial_extract')
print({'queued_document_ids': selected})
PY
```

Wait until the batch finishes, check each ID with `index_current()`, verify a page citation and log failures. Rerunning the bounded selector advances over completed documents within that 50-report window, not the entire backlog. For full catch-up, implement durable keyset pagination and a `financial_index` ledger; do not increase the window to load every report or keep retrying the same failed five forever. Prefer latest annual/interim reports for all covered companies before older archives. OCR reports require step 1's corrected shared-page indexing path.

## 7. Repair old numerical facts as a different lane

For each bounded company/report set: read retained PDF objects; extract v4 candidates into a review manifest; compare statement columns, reporting scales, fiscal periods, basis and durations; record original-row fingerprints; mark superseded originals unusable and insert reviewed replacements in one transaction. Use `services/financial_fact_repair.py`. Indexing can proceed independently but does not certify old facts.

Existing runner, with a reviewed manifest mounted read-only under `/srv/psx/import`:

```sh
docker compose -f compose.oracle.yml exec -T api python scripts/apply_financial_fact_repair.py /import/reviewed-financial-repair.json
# Check rollback-mode output and source-backed replacements before this apply:
docker compose -f compose.oracle.yml exec -T api python scripts/apply_financial_fact_repair.py /import/reviewed-financial-repair.json --apply
```

The filename is a concrete destination to create during review, not a manifest already present. The existing LUCK manifest covers only three reports; do not apply it as an all-company repair. Do not globally reset completed extraction states: the normal task skips old matching facts, and old facts must remain auditable. Repaired readers already exclude confidence-zero originals. Verify derived comparisons/cache invalidation after each batch.

## 8. Expand current sources, then August recovery, then deeper prices/fields

1. Observe at least 24 hours of the current canary; measure source poll age, publication-to-index lag, accepted/rejected counts, queue age, artifact/fact/index failures, database/spool growth and API responsiveness. Restart the intended services and verify work resumes before increasing concurrency.
2. Add repaired Mettis, Al Jazeera and Pakistan official releases to the allowlist one at a time; recreate every process that caches settings/SourceSpecs. Preserve 300s Pakistan reporting, 900s BBC/Guardian/global releases, 1800s shipping/energy and catalog-specific sector intervals. Do not silently change source cadences by starting a 30s scheduler heartbeat.
3. Add dated Pakistan and geopolitical archive adapters and durable weekly cursors; then recover August 1 onward. Existing `news_90d` only targets GDELT, which was throttled. Current RSS cannot recover August archives. Keep the seven-healthy-day historical breadth gate; then enable the historical worker with smaller budgets and current-work priority.
4. Backfill daily-price gaps against the reconciled eligible universe. Resolve the 244 absent original rows and three rejected rows using sourced status/alternate observations; do not fabricate missing OHLC. Resume the eight failed-history companies selectively after inspecting raw responses and fixing failure causes.
5. Expand report/history eligibility beyond the deep set only if full-market coverage is intended, with explicit resource bounds. Implement shares/market-cap, missing monthly Pakistan macro, additional commodity benchmarks, intraday quote/index and corporate-action contracts separately. Do not infer structured figures from RAG articles.

For every later deploy: record intended running services → stop producers → drain/preserve consumers → stop consumers → backup → exact-SHA deploy/migrate → recreate consumers → readiness/canary → resume only the intended producers. Automate that sequence in `deploy-oracle.yml` and `ops/ingestion`; today's workflow leaves ingestion off.

Related evidence: [source/company verification](audits/2026-10-03-source-contracts/README.md), [post–Phase 11 audit](POST_PHASE_11_INGESTION_AUDIT_AND_EXECUTION_PLAN.md), [targeted financial repair](audits/LUCK_FINANCIAL_FACT_REPAIR_2026-10-03.md).
