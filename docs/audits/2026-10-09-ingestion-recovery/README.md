# Oracle ingestion recovery — 9 October 2026

These are fresh read-only database checks, followed by explicitly authorized recovery work. Counts are a point-in-time snapshot; the running workers will change them.

## Price history and root cause

Initial selected, daily, exchange-local coverage: 748 active catalog entries; median 47 sessions; 247 without any selected daily history; 71 with at least 1,000 sessions. The zero count concerns daily history, not whether an intraday/latest quote exists. Every one of the nine symbols present in non-archived stored holdings already had approximately five years of history. The stored official October 8 capitalization workbook identifies 100 KSE-100 constituents; most still had only 41–47 sessions.

The legacy history ledger had 1,187 failed monthly units and four stale running entries from September 13. The unified pipeline had no `history_prices` stage runs. Empty source months were being retried for several old catalog symbols. No empty response is converted into a price or a completed historical period.

A concrete bootstrap bug compounds this: `upsert_company_from_price_row` assigned the discovery day to `Instrument.active_from`. Historical bootstrap then treated it as a listing-date bound. ABL, FFC, IBFL and ENGROH all had `active_from=2026-08-15` with no listing-date provenance, despite older source prices existing for FFC. A requested October 2021 start was therefore clamped to August 2026.

The local fix preserves catalog first-seen metadata separately. Historical requests only respect `active_from` when metadata explicitly marks a reviewed listing date and provides its source URL. Existing unverified stored dates are not silently rewritten. A reusable planner independently repairs the historical window using the current official constituent workbook and held symbols; its public outbox payloads contain security/month coordinates, never portfolio IDs or preferences.

## Live recovery started

`psx-price-priority-recovery-20261009` runs on Oracle using the existing API image and a reviewed standalone runner at `/srv/psx/import/price-history-recovery-20261009.py`. The runner is mounted read-only at `/app/price_history_recovery.py`; the correct script directory is needed for the existing application imports.

Requested window: October 1, 2021 through October 8, 2026. Five symbols per batch, at most 350 monthly tasks in flight, one check per minute, with a scoped share of up to four historical price dispatches per minute so shared document work cannot starve prices. Existing complete months require matching persisted observations. Partial months must actually reach the requested as-of date. Pending rows are not duplicated. Terminal source gaps are reported and skipped rather than trapping subsequent batches or being labelled complete. This coordinator is not a production image deployment; the durable bootstrap/discovery fixes are in the workspace for release.

Initial plan: 3,986 missing monthly windows for the priority universe, including verification of current partial months. After 49 completed monthly jobs, ABL increased from 47 to 834 selected daily sessions with a first date of October 1, 2021. This is progress, not full coverage: middle/later historical months were still queued. The coordinator then queued 237 more monthly jobs for ABOT, AGP, AHCL, AICL and AIRLINK and deferred the next batch when its in-flight budget was occupied.

The core services, pipeline scheduler, and seven Celery workers were running. The startup was verified earlier by Celery ping and web/API readiness. Starting containers alone had not populated the absent historical price outbox.

## Other verified blockers

- Statements/reports: 503 active catalog entries had no observed retained reports; 586 had no extracted facts; 620 had fewer than 50 facts. There were 7,964 historical report fetches already queued: duplicate blanket bootstrapping is not completion.
- Admission/budgets: 1,027 article fetches and 716 live report fetches were waiting on `daily_budget_deferred`, despite storage capacity allowing history. Storage had approximately 105 GB free and no capacity alert. The live byte allowance also applies to live-mode PDF acquisition; concurrent archived work must retain its proper mode.
- Narrative indexing: 363 report-index runs were dead-lettered with `ValueError`. All had admissible public observed documents and retained artifacts, but no indexed pages. Retaining a PDF or extracting numeric facts does not establish usable cited narrative. Native-only report indexing and scanned-report handling need source-level diagnosis.
- Re-extraction: `financial_extract` returns early for existing complete/partial extraction coverage and inserts facts only when the existing document/taxonomy/period/basis identity is absent. A parser fix followed by the same command does not automatically update incorrect existing values. Repairs need a versioned, source-reviewed replay/update path and preserved old-value provenance.
- Units: all sampled extracted fact rows are labelled PKR, which does not establish that their multipliers were correct. The extractor recognizes specific unit patterns and determines an initial page scale; local mixed-table scales and unrecognized parenthesized units require targeted fixtures and source re-extraction before relying on ratios. No old amounts were multiplied heuristically in this recovery.
- Macro: observed SBP coverage contained one `PK_TBILL_3M` point dated April 29, one KIBOR point dated August 13, and policy-rate observations through October 4. The risk-free resolver returned the April 29 point for October 8; it currently has no maximum-age check. The active local macro catalog also comments out `PK_TBILL_3M`. Fixing a lookup key alone neither refreshes that source nor enforces freshness. Prefer validated alternate SBP delivery contracts; do not substitute policy/KIBOR rates for T-bill yields.
- Events: the last-90-day stored cache contained 482 medium and 458 low `pipeline-v2` events, alongside older-version rows. Endpoint materiality/version/subject filters are distinct from document ingestion coverage. A bounded replay queued 80 classification runs and 20 section runs for retained recent news; incremental normalization scanned 100 retained raw events (64 classified, 36 unclassified). That does not manufacture company-specific news where source evidence is absent.
- Symbol/return quality: empty source responses for catalog names need identity/listing/alias reconciliation. Verified corporate-action adjustments remain incomplete; a five-year raw history is not proof of complete dividend-inclusive returns.
- Demo reseeding: `app.seed.demo` does more than refresh holdings. It creates synthetic macro/facts/events and sets instrument metadata to `synthetic_demo`. Do not use it as an unrestricted production price-repair command; isolate demo state and preserve observed instrument metadata first. It was not run while price recovery remained incomplete.

A small historical report/announcement batch was queued for ABL, ABOT and AHCL. Intelligence workers were already running. No extraction amounts, investor holdings, IPS records, LLM keys or trades were changed.

## Commands and validation

Once this module is in the API image:

```sh
python -m app.jobs.price_history_recovery --start 2021-10-01 --end 2026-10-08 --batch-size 5
python -m app.jobs.price_history_recovery --start 2021-10-01 --end 2026-10-08 --batch-size 5 --enqueue --watch --max-in-flight 350
python -m app.jobs.price_history_recovery --scope remaining --start 2021-10-01 --end 2026-10-08 --batch-size 5 --enqueue --watch --max-in-flight 350
```

Run `remaining` only after checking priority coverage/source gaps. CLI defaults are read-only; `--enqueue` is explicit. Existing schema is reused; no new migration or seed data is required. Standard backend migration remains `cd apps/api && alembic upgrade head`.

Offline validation:

```sh
DATABASE_URL='sqlite+pysqlite:///:memory:' EMBEDDING_BACKEND=hash apps/api/.venv/bin/python -m pytest apps/api/app/tests/test_price_history_recovery.py apps/api/app/tests/test_market_ingestion.py apps/api/app/tests/test_pipeline_news_priority.py apps/api/app/tests/test_pipeline_restoration.py -q
```

65 tests passed, including first-seen/listing separation, verified-date bounds, complete/partial period proof, monthly boundaries, idempotent enqueue, public payload isolation and advancement past terminal source gaps.

## Follow-up release and canaries

The ingestion repair was released as `ced33a6`, followed by the minimal missing-import build fix `ceb6d13`. Oracle rollout [37899240011](https://github.com/Raahim58/finance_project/actions/runs/37899240011) completed successfully. API and heavy worker report `financial-layout-v5-local-units`; readiness remains healthy. The corrected frontend release also passed an isolated production build. 92 targeted backend tests passed.

The versioned replay preserves original facts with zero active confidence and source/previous-confidence audit metadata. It installs new rows only from source-hash-verified deterministic extraction. Complete/partial extraction coverage only skips a document when its extractor version matches the installed version. Native-empty retained reports now use bounded OCR and explicitly label the limited OCR page coverage.

Live report canaries:

- LUCK, retained PDF `https://financials.psx.com.pk/lib/DownloadPDF.php?id=282262`: 42 active v5 facts; all 42 original rows retained inactive for audit.
- SYS, retained PDF `https://financials.psx.com.pk/lib/DownloadPDF.php?id=277949`: 20 active v5 facts; 16 original rows retained inactive for audit.
- MARI, retained PDF `https://financials.psx.com.pk/lib/DownloadPDF.php?id=275583`: explicit duplicate-year/date-column and accounting-basis ambiguities produced no admissible replacement rows. Eight legacy rows were retained but quarantined from active reads; extraction coverage is partial. The multi-period statement layout needs further repair before ratios can rely on that report.

Macro ingestion was already enabled, but its dedicated scheduler/worker were not running. Both were restored. Reactivating `PK_TBILL_3M` in the catalog and refreshing the official SBP provider yielded observed dates of September 30 (T-bill), October 8 (KIBOR) and October 9 (policy snapshot). No policy/KIBOR substitution for the T-bill input was introduced.

At the post-release check, 422 monthly price jobs had completed, one source gap was dead-lettered, and 298 were queued/running. Recovery remained active throughout the deployment. This is not a claim of completed universe-wide history, full statement coverage, resolved MARI layout, or complete corporate-action history. No production demo reseed was performed.
