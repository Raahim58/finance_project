# Oracle market and global ingestion audit — 2026-10-04

## Scope and evidence

**Sections 1–7 are the initial read-only audit. Section 8 records the subsequently authorized repairs and ingestion checks; it supersedes the earlier inactive-source status where explicitly stated.**

Read-only review of the current code, `docs/ORACLE_INGESTION_ACTIVATION_RUNBOOK.md`, the pasted October 3 source-contract report, and the deployed Oracle database/configuration. Oracle is on `ecf49f3`. No ingestion, queue publication, model calls, database updates, configuration changes or service starts were performed. This document is a proposal, not an activation record.

The shared ChatGPT URL could not be fetched; its contents were not reviewed. The pasted report matches the repository's [source-contract audit](2026-10-03-source-contracts/README.md). Its sampled source contracts are prior evidence, not fresh proof of every source's availability. A fresh Oracle GET confirmed DPS `/symbols` still returns HTTP 404, in 1.73 seconds.

Read-only database queries used `SET TRANSACTION READ ONLY` and session-local `max_parallel_workers_per_gather=0`. The latter avoids the already-known shared-memory failure during this audit; it changes no persistent database setting. Detailed temporary query output is in `/tmp/oracle-ingestion-audit-2026-10-04/state.jsonl` on the development Mac.

## 1. What apparently disappeared

**A market-date display regression is confirmed. The stored prices were not deleted.**

`services/market_service.py:get_latest_market_date()` takes the maximum canonical observation timestamp and calls `.date()` without converting to the source's trading date. The maximum is `2026-08-12 19:00 UTC`, which is August 13 at midnight in Pakistan. The recently corrected canonical reader now interprets that timestamp as August 13, but the latest-date resolver still chooses August 12.

| Live read | Result |
| --- | ---: |
| Market resolver's default date | August 12 |
| Canonical prices on that default date | 101 |
| Canonical prices on explicit August 13 | 600 |
| Default sector response | 39 sectors |
| Explicit August 13 sector response | 47 sectors |
| Legacy stored prices | 109,031 across 615 symbols |
| Selected canonical daily prices | 109,031 across 615 instruments |

The prior date correction changed reader interpretation, not stored timestamps. It was incomplete: the resolver must use the same trading-date contract. This is our code regression, separate from the longstanding ingestion gaps below. The observed row totals match the October 3 audit; that does not prove every historical row is byte-identical.

**Proposed minimal repair:** centralize source-observed trading-date/exchange-timezone resolution in `canonical_market_service.py` and use it in `market_service.py`'s default-date resolver and date query boundaries. Keep source exclusions consistent. Verify default prices, rankings and sectors against an explicit latest date using PostgreSQL fixtures with UTC timestamps representing Pakistan midnight. Do not shift stored prices or reimport them to repair this display issue.

## 2. Current coverage and genuine gaps

| Dataset | Verified Oracle state | Interpretation |
| --- | --- | --- |
| Company universe | 740 active; 493 have prices; 247 have none | Eligibility/aliases must be reconciled; absence does not prove deletion or current trading |
| Inactive records | 122, all priced | Current eligibility and retained historical records are different concepts |
| Price range | 2021-08-02 through 2026-08-13 | Range endpoints do not establish complete history for every symbol |
| Market capitalization | NULL in all 109,031 rows | OHLCV refresh alone will not fill this; validated shares/basis are needed |
| Standardized fundamentals | 18,320 facts across 625 instruments | Existing facts are usable where valid; this is not full balance-sheet coverage |
| Price-history ledger | 6,090 complete; 1,267 failed; 13 missing; 100 queued; 9 running | Old reservations and real persistence/parser failures remain |
| Reports | 1,391 annual/interim/quarterly documents; 16 have chunks | 1,375 reports have no chunks; creating their first index is not reindexing |
| Report associations | All 1,391 have NULL `company_id` | Existing symbol linkage matters; company-ID-only coverage queries can miss them |
| News | 116 documents, all with chunks | Global numerical history is much broader than narrative coverage |
| All chunks | 39,714; MiniLM-L6-v2, index version 2 | Preserve this model/version for incremental ingestion |

The previous source audit inspected the history failures: 1,176 had no validated OHLCV; 91 had integrity errors, including canonical-observation and sector-stat uniqueness conflicts. Do not blindly retry all of them: empty periods need classification as unavailable/pre-listing/no-trade versus parser/retrieval failure. The current audit reconfirmed aggregate states, not every raw failed response.

No ingestion workers/schedulers are running. API, web, PostgreSQL, Redis, MinIO and research-worker are running. Settings still disable macro ingestion, evidence ingestion and history bootstrap. `EVIDENCE_SOURCE_ALLOWLIST` is unset. Current-price mode is `auto`; fallback is not evidence that the primary source works or that all eligible securities are covered.

### Existing global data: extend this, do not rebuild it

The code catalog already has 27 series. The database also retains the earlier `PK_TBILL_3M` series. Selected sample coverage:

| Series | Stored rows | Stored endpoint |
| --- | ---: | --- |
| Brent daily | 6,753 | 2026-08-11 |
| Henry Hub daily | 6,681 | 2026-08-11 |
| US 10-year yield daily | 6,657 | 2026-08-13 |
| US CPI monthly | 318 | July 2026 |
| Fed funds monthly | 319 | July 2026 |
| US GDP quarterly | 106 | April 2026 period |
| World Bank crude/urea monthly | 319 each | July 2026 |
| Pakistan KIBOR | 1 | 2026-08-13 |
| Pakistan policy rate | 2 | 2026-08-17 |
| Pakistan net lending/GDP | 0 | None |

Most global histories start in 2000; the broad dollar index starts in 2006. These endpoints describe available periods, not publication dates or proof of gap-free coverage.

**Frequency/provenance issues must be addressed before claiming coverage:**

- `PK_USD_PKR` has 30 observations, 27 selected, spanning 2000–2026 while labelled daily; the catalog mixes an SBP current observation with annual World Bank fallback data. Reserves has the same annual/weekly mixing risk. An annual fallback cannot count as complete daily FX history.
- Stored Pakistan exports/imports/remittances are annual, while the current code catalog now requests monthly contracts. Existing annual observations must not be relabelled monthly by `ensure_macro_catalog()`.
- `TRADE_WEIGHTED_USD` uses FRED `DTWEXBGS`, a daily source, but is labelled weekly in the catalog and database. [FRED series metadata](https://fred.stlouisfed.org/series/DTWEXBGS).
- `persist_provider_result()` currently assigns `release_at=result.retrieved_at`. Retrieval time is not an observed historical publication time. Preserve retrieval time, but leave unknown release time unknown and distinguish retrospective history from evidence actually available at a past decision date.

Proposed change in `ingestion/macro_catalog.py`, `providers/macro/contracts.py`, `services/macro_ingestion_service.py`: require frequency, unit and period-basis compatibility before merging providers into one canonical series. Keep annual and monthly/daily variants as distinct identities, linked as related series. Preserve originals and source artifacts. Audit existing mixed records before remapping; do not manufacture daily observations, publication dates or monthly values from annual totals.

## 3. Runbook audit

The runbook is useful but **not executable unchanged**:

1. Its Oracle SHA and “allowlist not deployed” statements are stale. The control code is deployed at `ecf49f3`; the Oracle allowlist is still unset, so explicit source selection is not active.
2. It does not include the confirmed latest-date display regression or macro frequency/provenance issues above.
3. The DPS discovery repair remains a prerequisite: `/symbols` still returns 404. Repair against an observed ordinary source contract; do not bypass access controls or substitute an invented universe.
4. Historical news presets cover GDELT/PSX, not the proposed broad source list. Current RSS is not a historical archive. An authorized, dated archive adapter remains unimplemented/unverified.
5. Its rollout starts recurring current producers before August recovery. The user's current requested order is **historical catch-up first, then continuous daily ingestion**. A bounded current sample can test a contract beforehand; it is not live activation.
6. Deployment refuses ingestion-running releases and does not automatically restore ingestion services. Add an intended-service manifest and controlled producer pause, consumer drain/preservation, deployment and healthy resume sequence. A code push currently updates API/web, not an ingestion lifecycle.
7. The evidence spool is a named Docker volume rather than an explicit `/srv/psx` bind. Preserve pending files when moving it. PostgreSQL shared memory remains only 64 MiB; address this before heavier parallel queries/ingestion.
8. Proposed fetch/selection/raw-byte budgets are not a complete physical-storage policy. Shared reservations, database/vector growth, spool, logs, backups and every ingestion lane must participate in the headroom gate.

The runbook's new-report indexing repair is justified. `financial_extract` commits facts before publishing index work; a broker failure can leave reports unindexed. `prepare_report()` independently uses native text, losing the benefit of extraction's OCR pages. `index_current()` does check all existing chunks against the active version, but has no expected-content manifest proving that all intended pages/chunks were created.

Guardian archive access needs a key and use-case approval against its access terms. Do not assume the free developer tier automatically authorizes every AI/text-mining use case. [Guardian access terms](https://open-platform.theguardian.com/access/). The October 3 RSS sample passing does not verify archive entitlement or an archive adapter.

## 4. Recommended framework and exact implementation boundaries

**Keep PostgreSQL + Celery/Redis + MinIO + the existing local embedding model.** Three ingestion lanes share scheduling, provenance and physical-storage controls; their data models stay distinct. No Kafka, Airflow or per-item LLM generation is required.

| Lane | Reuse | Implement/repair |
| --- | --- | --- |
| Prices, indices, corporate actions | `market_providers.py`, `market_ingestion.py`, canonical observations, Instrument | Working DPS discovery; effective-dated security aliases/types; trading-date helper; concurrent upserts; real index history contract; sourced split/adjustment basis |
| Macro, commodities, currencies | `macro_catalog.py`, existing FRED/SBP/World Bank/ECB adapters, MacroSeries/Provider/Observation, macro scheduler/tasks | Frequency-compatible provider contracts, missing official historical adapters, source release metadata, gap-aware refresh |
| News, releases, reports | evidence pipeline/history service, SourceArtifact, Document/Page/Chunk, financial tasks, research evidence service | Authorized archive adapter; correct dates/body association/PDF route; durable save-to-index work; shared OCR/native pages; incremental index manifest |

### Durable work and truthful completeness

- Reuse `IngestionCoverage` for per-instrument work, and the existing macro/evidence run/slice ledgers for those lanes. Its instrument foreign key is mandatory: do not invent a company to hold global news or macro work.
- Give each work unit a unique dataset/source/entity/date-window/processing-version identity. Use PostgreSQL atomic insert/upsert and claims with leases; recover expired work. At-least-once task delivery must not duplicate observations or sector stats.
- Commit the durable next-stage work item with successful data writes. Publish after commit; a reconciler republishes pending/expired work. Redis delivery is transport, not the only record that indexing is needed.
- Add bounded partial refresh and typed failure reasons in `coverage_service.py`/task guards. Correct source/parser errors before selectively retrying their affected units. Keep intentional unavailable periods distinct from failed ones.
- Track source cursor, last successful attempt and complete-through window separately. A partial result must not advance “complete through” past an unexplained hole.
- Traverse the eligible universe/backlog using durable keyset cursors. Do not repeatedly sample the same first symbols or first 50 reports.

### Avoiding later wholesale reindexing

For narrative documents, persist an index manifest keyed by document, content hash, parser/chunker versions, embedding model/version and expected page/chunk counts. Give chunks stable identities from page/body content and chunk boundaries; record each stage's completion. Repeated delivery skips unchanged complete work and retries missing work. Correcting company/date metadata should update metadata/joins without regenerating vectors.

Keep the existing MiniLM model and index version 2 while activating ingestion. Share extraction's retained native/OCR page text with indexing, verify artifact hashes, and preserve source page numbers. Store changed source content as an auditable revision and index the changed content. First-time indexing of the 1,375 missing reports is its own bounded backlog, without re-extracting good numerical facts.

**Do not run `reindex_rag` for market imports or missing report chunks.** Prices/macro observations have no embedding requirement. This design avoids routine corpus-wide reindexing; changing the embedding model or incompatible chunking semantics later can still require a planned index migration.

### Initial breadth: concrete dataset scope

1. **PSX:** validate the current eligible universe; backfill daily prices for all verified eligible equities over the existing five-year target, bounded by genuine listing/trading availability. Held companies and the market benchmark go first, then the full eligible universe. Retain inactive historical securities and sourced aliases. Broad fundamentals stay broad; full-market historical fact repair remains separately deferred.
2. **Benchmark:** source real KSE-100 history before replacing the current individual-stock benchmark. Verify price-index versus total-return basis and calendar alignment; do not construct a purported index from current constituent weights. The historical feed contract is still a prerequisite, not verified ready in this audit.
3. **Pakistan macro:** genuine USD/PKR history, policy-rate change history, monthly CPI, treasury yields, reserves, monthly trade/current-account/remittances. Use verified official historical files; distinguish monthly/yearly variants. Existing current SBP key-indicator reads are not historical APIs.
4. **Global numerical context:** update the existing Brent, Henry Hub, US rates/inflation/GDP/unemployment, dollar index and ECB FX histories. Extend the existing World Bank workbook parser/catalog to coal, palm oil, cotton, LNG and other justified input costs, preserving actual source benchmark/unit/monthly frequency. Fetch/parse each shared workbook once per release, then fan out its series rather than download once per commodity. [World Bank commodity data](https://www.worldbank.org/en/research/commodity-markets).
5. **Global narratives:** start with the runbook's source selection: Pakistan business reporting; BBC/Guardian; Fed/ECB/BIS; EIA; shipping and selected sector publications. Use its sampled contract verdicts, repair gate/date/PDF issues first, and require fresh end-to-end source checks. Keep GDELT/AP/blocked sources dormant. Broader historical news needs an authorized archive; do not claim RSS polling backfills August.

This is relevant global investor context, not a promise of historical prices for every foreign listed company. Additional foreign equity/index exchanges require explicit exchange, adjustment, licensing and source contracts using the same lane.

## 5. Oracle capacity and scheduling

Verified hardware: 2 available CPUs, 11,927 MiB RAM, approximately 9,971 MiB available at measurement. Root: 48 GiB filesystem, 26 GiB free. Data disk: 147 GiB filesystem, 114 GiB free. Physical directories: PostgreSQL 1.5 GiB, MinIO 12 GiB, backups 421 MiB. PostgreSQL logical database size: 786,988,055 bytes (~751 MiB); chunks plus indexes ~452 MiB, canonical prices ~65 MiB, legacy prices ~38 MiB.

The deployed `s3` backend is MinIO on the Oracle block volume; it consumes that disk, not a separate OCI object-storage allowance. Current Oracle documentation lists 200 GB combined boot/block storage and A1 allowances equivalent to 2 OCPUs/12 GB; actual tenancy eligibility still comes from OCI Console, not this filesystem audit. [Oracle Always Free limits](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm).

Proposed initial operational limits:

- Network fetch concurrency 2 globally, additionally respect source-specific pacing; only 1 CPU-heavy OCR/embedding task at a time across workers. Do not independently give every queue two processes on a two-CPU host.
- Recreate PostgreSQL with `shm_size: 512m` while retaining its existing data bind; this expands the shared-memory ceiling, not a preallocation of all that RAM. Run representative queries and observe peak memory before increasing worker concurrency.
- Keep the runbook's new-news starting budgets: 100 fetches/day, 25 selections/day, 256 MiB downloaded raw bytes/day shared between historical/current news, 8 GiB retained new raw-news ceiling. Indexing has a separate measured growth/queue budget; raw-byte limits do not bound vectors.
- Backfill can use idle capacity before live activation; do not reserve 75% for nonexistent live work. After handoff, reserve 75% of news admission capacity for current work; historical work borrows only unused capacity and yields when current work is waiting.
- Before admission check `/srv/psx` free >=20 GiB and root >=8 GiB, plus estimated in-flight writes. Reserve response bytes before fetch and release unused reservation afterward; enforce hard streaming response caps. Include price/report/macro lanes in overall headroom even though their daily budgets differ.
- Measure physical database/index/object/spool/Redis/log/backup growth daily. Keep bounded diagnostic logs and rejected-fetch retention. Do not delete cited documents or source PDFs to disguise a capacity problem. Existing retained objects consume space too; an 8 GiB new-news allowance is not the entire MinIO limit.

The data disk currently has room for bounded backfill. No reliable completion time or long-term storage duration can be given from counts alone: obtain accepted rows/sec, bytes per accepted document, chunk growth, parser/embedding p50/p95 and queue ages from a canary first. Source 404s, archive availability and historical no-data classification are prerequisites, not worker speed problems.

## 6. Historical first, daily second: execution gates

1. **Repair contracts and readers:** latest-date resolver, DPS discovery/universe, concurrent writes, leases/partial refresh, macro frequencies and reliable new-document indexing. Preserve data and verify PostgreSQL concurrency/idempotency. Save complete raw-response fixtures for repaired contracts; the old diagnostic manifests are not full fixtures.
2. **Bounded canary, no continuous producers:** one current market date, one historical month for representative symbols, one benchmark window, each selected macro family, a native/OCR report and representative geopolitical/official/shipping news. Verify values, dates, provenance, expected coverage, searchable text and citations through application reads.
3. **Freeze the backfill manifest:** explicit source/entity lists, genuine earliest dates, fixed catch-up cutoff, parser/index versions and storage reservations. Proposed PSX target is five years; existing global numerical history remains 2000 onward where available. Proposed narrative recovery starts August 1, 2026 through the fixed cutoff, matching the existing runbook. Inaccessible weeks stay explicitly unavailable.
4. **Run historical consumers and bounded refill:** benchmark/held holdings first, then eligible-market missing windows; macro updates and verified archive slices; first-time report indexing separately. Reuse accepted data. Correct corporate actions before return/risk calculations. Finish/explain gaps against source calendars and eligible listing periods rather than demanding prices on closed days.
5. **Catch up and hand off:** advance the fixed cutoff to the handoff date, replay a small source-appropriate overlap idempotently, prove coverage and mark watermarks. Daily prices can replay the last 5 trading sessions; macro revisions need provider-specific overlapping release periods, not the same 5-day rule.
6. **Enable continuous producers only after gates pass:** dedicated market scheduler after exchange close for daily OHLCV, bounded catch-up retries and startup recovery; macro jobs according to actual publication frequency; news at existing source polling intervals; filings on the existing incremental catalog cadence. “Daily market ingestion” is not an intraday quote feed. Preserve the runbook's 300-second market polling proposal only if a separately verified current quote contract is actually wanted.
7. **Observe 24 hours before widening, then seven-day reliability:** restart/redeploy recovery, publication-to-index lag, market-date coverage, queue age, accepted/rejected reasons, growth and API responsiveness. Resume only intended services after deployment; no blanket `up` of every catalog source.

Acceptance: no unexplained missing eligible prices for the tested source dates; no false frequency/coverage claims; duplicate delivery and restart do not duplicate rows or lose indexing work; originals remain auditable; new news reaches retrieval with the right source/date; live handoff reuses historical data without a bulk embedding job.

## 7. Setup, migration and verification boundary

Read-only commands supported now:

```sh
ssh -i ~/.ssh/oracle_psx ubuntu@141.145.146.120
cd /home/ubuntu/finance_project
git rev-parse HEAD
docker compose -f compose.oracle.yml ps
docker compose -f compose.oracle.yml exec -T api alembic current
docker compose -f compose.oracle.yml exec -T api python -m app.jobs.macro_status
df -h / /srv/psx
free -m
```

When implementation is separately authorized: add migrations only for the needed work/index manifests and explicit macro provenance contracts; use the existing deployment command `docker compose -f compose.oracle.yml run --rm -T --interactive=false api alembic upgrade head`. It is not an instruction to run migrations or ingestion during this audit. Add PostgreSQL integration fixtures for date selection, duplicate delivery, leases, unique keys, rollback/broker failure and macro frequency incompatibility; retain the runbook's extraction/evidence regression checks. Recreate the database container for shared memory only after a verified backup/recovery point, preserving `/srv/psx/postgres`.

No new source adapter, scheduler module, migration or worker activation was implemented by this document. The recommended first code work is the small market-date resolver repair; the ingestion release follows the gates above. Full-company numerical fact repair, UI overhaul and model optimization remain outside this audit's implementation scope.

## 8. Authorized implementation and execution record

The user authorized starting repairs and ingestion and explicitly approved transfer of the sixteen API source files. Existing source was backed up at `/tmp/ingestion-source-before-20261004` on Oracle. Approved files were installed into the remote checkout and API image; API and research-worker were rebuilt/recreated without recreating PostgreSQL, Redis or MinIO. Initially these were uncommitted operator patches; the subsequent authorized commits are recorded in Section 9. No new migration or live LLM call was needed.

### Verified changes and imports

| Check | Observed result |
| --- | --- |
| DPS public contract | Published `window.__ps._k` session header restores `/symbols` and historical POST requests; no authentication/access-control bypass |
| Current prices | 467 accepted securities on October 2; 747 attempted directory symbols; eligibility/obsolete-symbol reconciliation still pending |
| Default market date | October 2; 467 prices returned after resolver repair |
| Representative history | LUCK, FFC, MEBL, OGDC, HBL, HUBC, ILP, MARI, SYS: 19 August and 22 September observations each |
| Additional global series | Coal (Australia), palm oil, cotton A-index, LNG (Japan), copper: 321 monthly observations each, January 2000–September 2026 |
| Workbook batching | One 586,099-byte World Bank fetch for all five series; repeat writes add zero observations; total import/replay 10.79 seconds |
| Current global narrative canary | Nine selected articles across seven source categories; the malformed ECB PDF revision was quarantined and correctly replaced |
| Corrected ECB PDF | New revision `fa68c77c-74d1-4e26-95d4-2287009c232f`: 11 physical pages, 4,230 text characters, 11 chunks, 14.97 seconds; invalid 1,259-chunk revision retained but excluded from retrieval |
| Dated archive | One gCaptain and two FreightWaves August articles fetched, parsed and selected through durable historical requests; FreightWaves pricing/capacity gate repair verified end to end (20.36 seconds with model warmup, then 4.27 seconds) |
| Regression suite | 154 targeted tests pass, including archive/source identity, admission, native PDF pages, metadata boundaries, historical coverage and macro providers |
| App readiness | `http://127.0.0.1:13000/api/ready`: database, Redis, artifacts all `ok`; existing tunnel remains available |
| Disk headroom | Root 26 GiB free; data volume 114 GiB free during catch-up |

Writer repairs use PostgreSQL transaction advisory locks across canonical/legacy prices and derived sector stats, and scoped locks for coverage creation. Two concurrent real-price replays completed without constraint failures: the first differing normalized representation created five source observations, the identical second created zero. That check proves serialization/idempotency for identical payloads, not that different normalized payloads share one artifact identity. Existing source artifacts and numerical records are retained.

The latest-date resolver uses source trading-date semantics. Monthly history no longer reassigns observation identity to an unrelated lookback artifact; normalized provenance links retain all raw response IDs. Mid-month “complete” entries are revisited after month end, and open months remain partial. Explicit refresh intervals control partial refresh rather than unlimited retries.

Global relevance uses whole terms and specific transmission channels, not a globally lowered threshold. Confirmed geopolitical and freight-market false negatives were fixture-tested against unrelated sports/coalition/truck-crime headlines. PDF magic/content type routes to the native parser; retained physical page numbers produce citations. Selected-source admission no longer treats dormant-source backlog as current pressure. The new archive preset includes source selection in request identity and uses raw publisher offsets even when UTC date filtering removes an overlap page.

### Running recent-market catch-up

One isolated Celery worker, `psx-market-recent-catchup`, consumes `market_recent_catchup_20261004` with concurrency 1. The fixed manifest is `/srv/psx/backups/market-recent-catchup-20261004.json` (container path `/backups/...`). It contains 467 securities actually observed on October 2 and 916 incomplete August/September month units after excluding the eighteen completed demo units. This is a bounded catch-up, not full five-year coverage or proof every current directory record is eligible. Existing queues were not purged/reset. Early jobs complete in roughly 3–4 seconds per month; failures remain recorded in the existing coverage ledger.

Operator checks:

```sh
ssh -i ~/.ssh/oracle_psx ubuntu@141.145.146.120
cd /home/ubuntu/finance_project
docker logs --tail 40 psx-market-recent-catchup
docker compose -f compose.oracle.yml exec -T redis redis-cli LLEN market_recent_catchup_20261004
docker compose -f compose.oracle.yml ps api research-worker
curl --fail http://127.0.0.1:3000/api/ready
df -h / /srv/psx
```

Do not republish the entire manifest merely because the browser disconnects. Inspect task outcomes/coverage and active/reserved work first. Retain the manifest and distinguish queued units from completed ones. After the queue drains, stop the one-off worker; continuous producers must pass the remaining activation gates.

### Still required before continuous handoff

Finish and audit the running recent-market manifest; classify genuine unavailable periods and remaining invalid OHLCV. Reconcile the current directory rather than calling all 280 missing/special entries failures. Verify a genuine broad-market index contract; HBL history is now available for the tested recent months, but HBL is still not a market-index benchmark. Complete historical archive slices within their per-source budgets (six fetches/three selections per source per day currently constrain the shipping sources); preserve deferred items and never mark an unfinished cursor complete.

Macro frequency/release-provenance issues, missing report first-time indexing, full five-year gaps, source-specific source/date repairs, independent daily market scheduling, spool relocation, PostgreSQL shared memory, storage/retention enforcement and deployment pause/resume remain open. Continuous schedulers were not enabled by these canaries. Preserve the initial audit/runbook scope; do not claim those gates passed because the bounded imports succeeded.

## 9. Committed release and live coverage snapshot — October 4, 16:15 Pakistan time

Code commits: `320c023` (PSX contracts, dates and writes), `2b8b325` (five commodity histories), `33a114a` (global relevance, PDF handling and dated archives). The final combined targeted suite passed: **154 tests in 11.95 seconds**. This section is a measured snapshot while the worker runs; totals can increase afterward.

| Data stored now | Coverage and practical limits |
| --- | --- |
| PSX daily prices | 118,909 rows across 621 symbols; overall range August 2, 2021–October 2, 2026. Different companies have different gaps; range endpoints are not continuous coverage. Latest-date sample contains 467 securities. |
| Standardized company financials | 18,320 facts across 625 companies. Secondary DPS figures; not every company/period/metric is complete or validated. |
| Issuer-report financial facts | 14,418 facts across 116 companies. Exact numerical retrieval uses these database records independently of document search. |
| Original company reports | 507 annual, 882 quarterly, 2 interim: 1,391 reports retained. Only 16 currently have indexed text; 1,375 still need first-time text indexing. |
| Announcements and news | 6,244 announcement documents and 129 news documents. The news count includes the quarantined malformed PDF revision, whose 1,259 chunks are excluded. New evidence includes geopolitical/shipping disruption, freight pricing/capacity, central-bank decisions, banking regulation, energy and trade/tariff stories. These counts do not establish broad company-by-company timely news coverage. |
| Search index | 39,800 chunks have status `indexed`; 1,259 quarantined chunks have status `failed`. Production uses the existing semantic embedding model; no corpus-wide reindex was performed. |
| Macro catalog | 33 persisted series, including the older treasury-bill series; 32 have selected observations and Pakistan net-lending/GDP has none. Units/frequencies and actual observation dates must be respected. |

### Numerical global/Pakistan datasets and dates

| Group | Available data | Last stored periods |
| --- | --- | --- |
| New commodity histories | Australian coal, palm oil, cotton A-index, Japan LNG, copper; 321 monthly observations each from January 2000 | September 2026 |
| Other commodities | Brent daily (6,753), Henry Hub daily (6,681); World Bank crude/urea monthly (319 each) | Daily series August 11; monthly series July 2026 |
| US market/macro | US 10-year yield (6,657), broad trade-weighted dollar (5,164), CPI (318), unemployment (318), Fed funds (319), real GDP (106) | Yield August 13; dollar August 7; monthly data July; GDP April 2026 period |
| European FX | USD/EUR series with 319 selected observations | July 2026; current registered frequency/source contract needs checking before describing it as daily ECB coverage |
| Pakistan longer-run context | Annual GDP growth, inflation, unemployment, exports/imports, remittances, FDI, current-account/GDP, mostly 26 observations from 2000 | Mostly 2025; these are annual context, not monthly/current replacements |
| Pakistan rates/FX/reserves | Policy rate (2), KIBOR (1), treasury bill (1), USD/PKR (27 selected), reserves (27 selected) | Sparse current samples plus annual fallbacks; not reliable daily/weekly historical series as currently labelled |
| Pakistan government finance | Debt/GDP has 2 selected old observations; net lending/GDP has none | Debt dates 1998/2000; insufficient current coverage |

### What the running batch adds, and what it does not

The fixed target is **934 company-months (467 securities × August/September)**. Eighteen demo-company months were already completed before the manifest, leaving 916 submitted tasks. At 16:15 Pakistan time, **506 target months met the closed-month completion check**, **423 tasks were still queued**, and four newly attempted September units failed because DPS returned HTML without `#historicalTable`: ANSM, BAFL, COLG, KHTC. Those are unexpected response/parser-contract failures; their ultimate source availability is not established. Older ledger `IntegrityError` entries remain for not-yet-reprocessed units; do not confuse them with a new failure of the writer repair.

Successful completion adds each target's available valid August/September OHLCV and source provenance into the existing canonical/legacy price stores, filling gaps rather than duplicating all prior data. Failures remain explicit. The nine representative companies have 19 August and 22 September rows each; other securities can have fewer due to actual listing/trading/source availability. No guaranteed final row count is asserted before the batch finishes.

This worker does **not** ingest October 1 history for the full universe (the October 2 current snapshot is already stored), repair all older five-year gaps, import KSE-100/total-return benchmark history, adjust stock splits, calculate missing market cap, refresh all macro series, index the missing reports, perform comprehensive financial-fact repairs, backfill every news source or start continuous daily ingestion. Those remain separate jobs/gates.

### Priority gaps after the batch

1. Verify catch-up failures against retained/observed DPS responses, then complete October trading sessions and classify older price gaps. Reconcile current eligible securities and preserve inactive/renamed historical records.
2. Import a genuine broad-market benchmark and sourced corporate actions/adjusted return basis. Raw split discontinuities must not be interpreted as losses in risk analytics.
3. Establish genuine Pakistan policy-rate, FX, CPI, reserves and monthly external-sector history; separate annual fallback series from daily/monthly contracts. Refresh the existing global numerical series through their latest available releases.
4. Index the 1,375 retained reports lacking searchable text without re-extracting valid financial facts or rebuilding the whole index. Improve timely company/global news breadth; the new shipping archives have only bounded verified samples so far.
5. Add independent continuous market scheduling and finish the runbook's storage, spool, shared-memory, retention and deploy pause/resume controls. Current continuous producers remain off; the isolated bounded history worker continues running.

## 10. Saved sequencing decision and benchmark scope

Saved at the user's request on 2026-10-04. This is an execution-order decision, not a claim that the remaining work has been performed:

> These are different jobs. We can run backfills alongside implementation, but the two-CPU Oracle server should have only one heavy OCR/embedding worker. Estimates below are planning ranges, not measured completion promises.
>
> My order: finish recent-price failures, get KSE-100 and split handling right, then run report indexing + broader news + macro imports alongside each other within resource limits. Enable each verified live lane as it becomes ready—we shouldn't wait for every five-year historical gap to close.
>
> The main uncertainty is source availability and OCR volume, not writing another scheduler. I can defend the price throughput estimate from actual runs; the report/news estimates still need representative timing samples.

The user selected **both KSE100 and KSE100PR, with all available official daily history**. Keep total-return and price-return series distinct, with source provenance. Historical download availability remains to be verified; benchmark usage, missing-date policy and split handling are still being settled section by section. Do not silently substitute a stock for either market index.

Report indexing already exists through `financial_index` / `prepare_report`, but the documented five-report selector only considers the latest 50 candidates. `prepare_report` currently extracts native PDF text, not OCR. A full backlog pass must paginate beyond that window, skip current indexes, record failures and process one report at a time on Oracle. It must not re-extract numerical facts or run corpus-wide `reindex_rag`.
