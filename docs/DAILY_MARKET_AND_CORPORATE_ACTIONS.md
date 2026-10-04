# Daily market data and corporate actions

Scope: daily company prices and both official KSE-100 variants, verified share/capitalization observations, and source-backed corporate actions. Tavily and UI work follow later. No model calls or portfolio ledger mutations occur in this worker.

## Daily operation

The dedicated `market-scheduler` polls every ten minutes. Its target is the most recent weekday after 18:15 Asia/Karachi; before that time it targets the preceding weekday. This is end-of-day ingestion, not intraday quotes. A durable per-stage/date ledger prevents repeat successful downloads; unsuccessful stages wait two hours before retrying. PostgreSQL coordination prevents overlapping scheduler instances. Source holidays/empty responses remain failed/unavailable rather than being labelled complete. Missing symbols and rejected source rows remain visible in diagnostics even when a date-wise fetch succeeds.

Five recent weekdays are checked independently to recover short outages. Each price request addresses that exact date: it cannot silently substitute another trading date. Older symbol/month recovery remains the separate resumable history lane. Exact repeated source history rows are deduplicated; conflicting same-date rows fail for review.

The stages commit separately: company prices, KSE100 and KSE100PR current-month history, dated capitalization workbook, recent payout announcements. The worker does not invoke the broad legacy scheduler, research ingestion, screening, model calls, or corporate-action ledger application.

## Shares and capitalization

Source: official DPS `/download/indhist/YYYY-MM-DD.xls`. Total ordinary shares come exclusively from `KSE-ALL-Shares`; index sheets sometimes label free-float shares as ordinary shares. Index sheets supply their published percentage weights only. Validate finite prices, integral nonnegative shares/volume, free float no greater than ordinary shares, and capitalization arithmetic. Retain source workbook, digest and observation date. Invalid records are quarantined; unrecognized symbols are recorded, not invented.

Latest price retrieval includes shares, float, capitalization and source metadata only for a matching price/snapshot date. No future snapshot can leak into historical prices. Raw market observations stay unchanged.

## Corporate actions

Official DPS `/payouts` supplies percentages, announcement timestamps and book closures. Those fields do not prove ex dates, cash per share or settlement dates. Store dividend/bonus/rights announcements with explicit missing execution fields. These announcement types are ineligible for price adjustment or ledger application. Conflicting revisions are flagged for review.

Reviewed actions use `ops/oracle/reviewed-corporate-actions.json`. The importer verifies pinned source PDF hashes, exact page excerpts, dates and numeric split/bonus multipliers. SYS's 5-for-1 split is sourced to the June 2, 2025 issuer credit notice (May 31 effective). MARI's 800% bonus uses the explicit September 16, 2024 ex-date in the official September 13 daily quotation calendar. Gross bonus adjustment does not credit investor holdings or assume tax treatment. Original prices remain raw; analytics apply verified split/bonus factors to preceding observations only. Existing LUCK handling remains intact.

This is not a complete all-company corporate-action history. Unreviewed announcements are not applied. Dividend cash amounts/payment dates and dividend-inclusive total-return calculations remain distinct from the split/bonus-adjusted price view. Do not describe that view as a total-return series.

## Setup, deployment and verification

Existing dependencies and schema are reused; no migration is added. To bring an older installation to the existing schema:

```sh
docker compose -f compose.oracle.yml run --rm api alembic upgrade head
```

On Oracle after reviewing/transferring the source files:

```sh
docker compose -f compose.oracle.yml build api
docker compose -f compose.oracle.yml up -d --no-deps api
docker compose -f compose.oracle.yml run --rm -T -v "$PWD/ops/oracle:/reviewed:ro" api python -m app.jobs.reviewed_corporate_actions --manifest /reviewed/reviewed-corporate-actions.json
docker compose -f compose.oracle.yml run --rm -T api python -m app.jobs.market_daily --once --payouts-backfill
./ops/ingestion start market
./ops/ingestion status
```

`--payouts-backfill` reads the actual publicly available archive in pages of 100, capped at 10,000 source rows. It makes no claim to recover unavailable earlier years. Re-running completed pages reuses their durable results; `--once --force` explicitly revalidates. Source content remains deduplicated and immutable.

Offline checks:

```sh
cd apps/api
DATABASE_URL='sqlite+pysqlite:///:memory:' EMBEDDING_BACKEND=hash .venv/bin/python -m pytest app/tests/test_market_daily.py app/tests/test_index_and_splits.py app/tests/test_market_providers.py app/tests/test_market_ingestion.py app/tests/test_canonical_market.py app/tests/test_market_api.py -q
```

Before calling deployment complete, verify actual source-backed row counts, date/coverage diagnostics, idempotent reruns, action-adjusted price continuity and an operating scheduler. Keep the existing news worker concurrency unchanged.
