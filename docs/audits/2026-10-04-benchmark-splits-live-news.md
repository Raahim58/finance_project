# DPS benchmark, sourced splits and filtered live news — 2026-10-04

## Verified source contract

Use `DpsMarketDataProvider._client()` to establish DPS's public session and request headers. Bare requests incorrectly returned 404/403. Both `KSE100` (published total-return index) and `KSE100PR` (price-return index) have working `/historical` monthly tables and `/timeseries/eod/...` closing series. The EOD series supplies close, volume and open, not high/low. Monthly tables supply OHLC and volume. Preserve their distinct return bases.

The official daily-download constituent workbook also supplies prices, weights, free-float and ordinary shares, market capitalization and volume. Its sheets are constituent snapshots, not historical index levels. These fields were inspected; importing them is separate from the current index/split change.

## Implementation and data-quality decisions

`app.jobs.index_backfill` imports sequential months and persists each result in `IngestionRun`. Completed closed months resume without re-fetching. Source responses remain immutable artifacts. Valid full OHLC observations and independently validated daily closes are stored separately; `close_series` supplies closes for benchmark calculations without fabricating OHLC.

Confirmed DPS defects:

- KSE100 May 15, 2023: published close 41,718.43 exceeds high 41,716.26. Keep the valid dated positive close; record an explicit OHLC quality issue. Do not raise the high artificially.
- KSE100 January 22, 2024: the monthly table repeats an identical six-field row. Deduplicate exact rows. Conflicting rows for the same date still fail the month.

Recent history command, entirely on Oracle:

```sh
docker compose -f compose.oracle.yml run -d --no-deps --name psx-index-recent-final-20261004 api python -m app.jobs.index_backfill --symbol KSE100 --symbol KSE100PR --date-from 2021-07-01 --date-to 2026-10-04
```

The first run imported KSE100 July 2021–April 2023 before the OHLC defect. The revised run reached December 2023 before the duplicate defect. The final revision is deployed. Recent imports for both variants completed through October 2, 2026: 1,302 dated closes each for July 2021 onward, and zero missing dates against each demo portfolio's 1,269-date sample. Older history is a separate running job; neither index is certified complete back to inception.

Both demo portfolios now use KSE100 after the alignment check. Each has successor IPS version 2 with all other constraints and required return preserved; original version 1 remains saved and the change is audited. HBL is an individual stock and had only one canonical price at the earlier audit; it is not a market proxy.

## LUCK split — recorded on Oracle

Official annual report document `691d4ca7-abd2-4103-851d-4e545132b58d`, page 148, explicitly confirms a 5-for-1 split effective April 28, 2025. Source: https://financials.psx.com.pk/lib/DownloadPDF.php?id=258917 . The quote and source artifact are retained in corporate action `4f7bc6d4-420a-4b72-8b02-50461dba052b`.

Raw April 18/April 28 closes: 1,751.45 / 358.88. Split-adjusted prior close: 350.29. The analytical return is +2.45225%, instead of the raw mechanical -79.5095%. Raw quotes remain unchanged. Existing ledger application found zero eligible pre-split demo positions; no holdings were altered.

The generic analytical adjustment applies only source-reviewed recorded splits, compounds multiple ratios and ignores future actions beyond the analysis cutoff. Raw volumes remain raw share units. This is not a claim of complete dividend/bonus/corporate-action coverage for other companies.

## Live news implementation and verified activation

`EVIDENCE_MATERIAL_NEWS_ENABLED` defaults false. When enabled, shared discovery rejects immaterial titles before downloads; fetch handles older pending candidates; parse validates substantial body text, publication date, a seven-day live window, relevance and subscription previews. Historical requests retain their explicit archive windows. PSX announcements do not receive the article filter.

Reuse deterministic source discovery, relevance tags, deduplication and document indexing. No article-by-article LLM call. Source ceilings: 300 discoveries, 40 fetches, 20 selected/day. Existing global ceilings remain 2,000/250/75 with byte/headroom limits. Ceilings are not relevance targets. Review accepted/rejected samples; keyword rules cannot guarantee exhaustive coverage or investment relevance.

Started discovery(1), fetch(2), parse(1), index/OCR(1) and the evidence scheduler after source deployment and benchmark verification. Do not also start the PDF worker. Compose restart policies now support those news services surviving reboot. Existing scheduler priority puts live candidates before historical work.

```sh
docker compose -f compose.oracle.yml --profile ingestion --profile scheduling up -d --no-deps worker-evidence-discovery worker-evidence-fetch worker-evidence-parse worker-evidence-index evidence-scheduler
```

All ten selected sources completed a successful first poll with zero recorded source failures: Dawn, Business Recorder, BBC, Guardian, gCaptain, FreightWaves, World Fertilizer, World Cement, OilPrice and Cotton Grower. Initial new-candidate outcomes: 21 selected, 163 rejected and 14 duplicate. Samples created searchable chunks in 23–36 seconds after discovery. Rejections are expected: frequent polling is not a quota to fill. Actual RAG search returned new source-linked Hormuz articles. Continue monitoring subsequent polls, rejection samples, queue delay and discovery-to-searchable latency. Historical archive completion is not a prerequisite for each verified live lane.

## Checks and deployment status

82 targeted tests passed for index/split ingestion, portfolio calculations, allocation, retrieval and evidence stages, including the discovery-filter test. `git diff --check` passed. No live LLM calls. No schema migration is introduced; deployment retains the existing migration head.

Oracle had 25 GiB root and 113 GiB data-volume free, with low load at the last successful read. Large source uploads stalled; the unchanged approved archive was transferred in small chunks and SHA-verified before extraction. The current API and news workers run the tested revision. Port 13000 readiness returns database/Redis/artifact checks OK. Live allocation comparison of unchanged weights yields beta 0.832598 for the Decision demo and 0.828617 for the Main demo. No trades or holdings were changed.

## Older index backfill status and remaining scope

Container `psx-index-older-20261004` sequentially imports KSE100 January 1991–June 2021, then KSE100PR April 2009–June 2021. Monthly empty responses are retained as source observations, not described as proof no historical values ever existed. The first nonempty older KSE100 sample observed in this run starts January 2008; 1991–2007 returned empty tables. As of the last read, KSE100 had 1,364 total dated closes and the job was still running. Durable month records allow resuming failures without restarting complete months.

```sh
docker logs --tail 5 psx-index-older-20261004
docker inspect -f '{{.State.Status}} {{.State.ExitCode}}' psx-index-older-20261004
```

Remaining: certify older-history coverage when the job finishes; review more accepted/rejected news samples over subsequent polls; add further source-reviewed corporate actions beyond LUCK. Existing `portfolio_quant` still gates its combined regression/ratio block on a risk-free observation, although the allocation comparison beta path no longer lacks benchmark inputs. This separate availability gate has not been silently changed. The pre-existing market-price catch-up container inherits an HTTP API readiness healthcheck even though it is a Celery worker; its unhealthy label alone does not establish a job failure. Current work does not claim live daily-price scheduling or that catch-up complete. Shares/market-cap workbook ingestion, report OCR/backlog and other deferred follow-ups remain separate.
