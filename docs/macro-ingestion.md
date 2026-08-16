# Canonical Macro Ingestion

The macro pipeline is independent from Global Evidence. GDELT and Mettis are
document/event discovery sources, and SEC is a company-filings source; none of
them is allowed to determine whether an exact macro series exists.

The pipeline currently registers 26 source-independent series. A canonical key
such as `PK_CPI_YOY` owns an ordered provider ladder rather than belonging to one
website:

```text
PK_CPI_YOY
  PBS aggregate workbook (priority 10; disabled until its exact contract is verified)
  IMF DataMapper       (priority 20; disabled after verified HTTP 403)
  World Bank API       (priority 30; enabled fallback)
```

All successful provider observations are retained. The selected observation is
the successful provider with the lowest numeric priority. If values disagree,
the pipeline preserves both values, selects the higher-authority row, and creates
a `macro_provider_disagreement` data-quality issue. It never silently splices or
overwrites conflicting values.

Each observation records its provider, original series ID, retrieval time,
vintage when supplied, authority, confidence, raw source artifact, and selection
reason. Exact values continue to come from database queries, never RAG.

## Implemented contracts

| Provider path | State | Use |
|---|---|---|
| World Bank Indicators JSON API | Enabled and live-smoke verified | Pakistan and global annual fallbacks |
| FRED observations API | Enabled when `FRED_API_KEY` is set | U.S. macro; API key is never stored in provenance |
| FRED official CSV download | Enabled without a key | U.S. macro and EIA-origin Henry Hub/Brent copies |
| ECB Data Portal SDMX CSV | Enabled; parser fixture tested against the documented contract | USD/EUR macro FX |
| SBP key-indicator HTML | Enabled | Current policy rate and observed 3-month MTB yield |
| World Bank Pink Sheet XLSX | Enabled | Crude-oil average and urea prices |
| IMF DataMapper | Contract/parser retained but disabled | Runtime returned persistent HTTP 403; World Bank fallback remains active |
| PBS/SBP aggregate workbooks | Ladder slots retained but disabled | Exact workbook/table contracts are not yet fixture-verified |
| EIA v2 | Disabled | API key is required and the exact Henry Hub route/shape still needs a fixture; FRED's official EIA-origin copy is active |

BIS, OPEC, broader PBS/SBP, NEPRA, and OGRA series remain explicit next adapters.
They must not be marked enabled until the real response, units, revisions, and
date conventions are captured in a bounded fixture. This prevents a guessed URL
from creating another scheduler that appears healthy while writing zero rows.

## `.venv` operation

Run the migration once:

```bash
cd apps/api
source .venv/bin/activate
alembic upgrade head
```

Configure `.env`:

```bash
MACRO_INGESTION_ENABLED=true
MACRO_SCHEDULER_SECONDS=30
MACRO_QUEUE_TARGET=8
MACRO_HISTORY_START_YEAR=2000
FRED_API_KEY=
```

The FRED key is optional because the official CSV fallback is enabled. Start one
thread-pool worker (avoids macOS/Python prefork crashes) and the dedicated queue
producer in separate terminals:

```bash
cd apps/api
source .venv/bin/activate
celery -A app.celery_app worker -P threads -n macro@%h -Q macro --concurrency=4 --loglevel=INFO
```

```bash
cd apps/api
source .venv/bin/activate
MACRO_INGESTION_ENABLED=true python -u -m app.jobs.macro_scheduler
```

Read progress without changing state:

```bash
python -m app.jobs.macro_status
```

For a bounded queue-publication smoke cycle only:

```bash
MACRO_INGESTION_ENABLED=true python -u -m app.jobs.macro_scheduler --once
```

The scheduler creates at most `MACRO_QUEUE_TARGET` outstanding tasks. Daily run
keys make publication idempotent, stale leases are recovered from Postgres, and
each series is retried independently. Existing evidence workers and schedulers do
not consume or publish the `macro` queue.
