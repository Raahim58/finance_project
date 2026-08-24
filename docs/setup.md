# Setup

## Backend

```bash
cd apps/api
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp ../../.env.example .env
python -m app.core.keys
```

Put the generated Fernet key in `ENCRYPTION_KEY`. User LLM keys are encrypted at rest, never returned after save, and decrypted server-side only for an LLM request.

Start production-style dependencies and migrate:

```bash
cd ../..
docker compose up -d
cd apps/api
alembic upgrade head
```

SQLite can be used without Docker:

```bash
DATABASE_URL=sqlite+pysqlite:///./psx_ai_local.db alembic upgrade head
```

Seed the demo investor state (demo user, ledger-backed holdings and cash,
historical cost basis, investor profile, confirmed IPS, target allocation, and
monitoring preferences). This default path creates no market prices, macro
observations, company reports, financial facts, or events:

```bash
DEMO_USER_PASSWORD='choose-a-local-password' python -m app.seed.demo
```

The demo login is `portfolio.manager@example.com`. The command is idempotent and
never seeds an LLM key. Run live ingestion after this command to create the
hybrid environment: synthetic investor state plus observed external-world data.

For isolated offline development only, the old deterministic external-world
fixtures remain explicitly available:

```bash
DEMO_USER_PASSWORD='choose-a-local-password' python -m app.seed.demo --with-mock-world
```

Never use `--with-mock-world` in an `auto`, `dps`, or other live-data database.
Even if old mock rows exist, live modes exclude them from canonical prices,
market screens, portfolio valuation, and quant inputs.

Run the API, scheduler, and the four Phase 2 queues in separate worker pools:

```bash
uvicorn app.main:app --reload
celery -A app.celery_app worker -Q broad_fundamentals --concurrency=20 --loglevel=INFO
celery -A app.celery_app worker -Q dps_history --concurrency=24 --loglevel=INFO
celery -A app.celery_app worker -Q financial_download --concurrency=12 --loglevel=INFO
celery -A app.celery_app worker -Q financial_extract --concurrency=3 --loglevel=INFO
python -m app.jobs.scheduler --once
python -m app.jobs.scheduler
python -m app.jobs.phase2_scheduler
```

Canonical macro ingestion has its own Postgres-led queue producer. It does not
depend on the document/evidence scheduler:

```bash
celery -A app.celery_app worker -P threads -n macro@%h -Q macro --concurrency=4 --loglevel=INFO
MACRO_INGESTION_ENABLED=true python -u -m app.jobs.macro_scheduler
python -m app.jobs.macro_status
```

Provider ladders, exact current coverage, fallbacks, and the bounded one-cycle
command are documented in [Canonical Macro Ingestion](macro-ingestion.md).

The live universe is synchronized from observed DPS symbol data; there is no configured stock list. Expensive history/report work is reconstructed from Postgres coverage rows after a Redis loss. Docker Compose persists Postgres, Redis AOF data, and source artifacts in named volumes. Its lightweight `phase2-scheduler` is the sole Phase 2 queue producer: it checks queue targets every two seconds, reserves coverage rows before publication, completes historical report-catalogue bootstrap once, and performs bucketed incremental current/prior-year catalogue refreshes every six hours. The five-minute market scheduler remains separate and never publishes Phase 2 tasks.

`MARKET_DATA_MODE=mock` is development-only. `dps` uses the verified direct DPS adapter; `auto` tries DPS and uses Yahoo only as a labeled real-data fallback. A failed live refresh retains prior observed rows and records failure/staleness; it never generates mock replacements. NCCPL remains a manual CSV import because ordinary retrieval is blocked; no anti-bot bypass is implemented.

DPS latest-price coverage uses the currently observed DPS ordinary-equity universe
as its denominator. A response that omits any ordinary symbol is recorded as
`partial` with the missing symbols and accepted/rejected counts; Yahoo or SCSTrade
rows never satisfy DPS health. DPS standardized company-page facts are exposed as
observed secondary fundamentals, while facts extracted from official filings retain
precedence for the same metric and period.

Enable and run the independent Global Evidence services with a shared artifact/spool
volume:

```bash
EVIDENCE_ENABLED=true python -m app.jobs.evidence_scheduler
celery -A app.celery_app worker -n discovery@%h -Q evidence_discovery --concurrency=4 --loglevel=INFO
celery -A app.celery_app worker -n fetch@%h -Q evidence_fetch --concurrency=16 --loglevel=INFO
celery -A app.celery_app worker -n parse@%h -Q evidence_parse --concurrency=6 --loglevel=INFO
celery -A app.celery_app worker -n pdf@%h -Q evidence_pdf --concurrency=2 --loglevel=INFO
celery -A app.celery_app worker -n index@%h -Q evidence_index --concurrency=4 --loglevel=INFO
celery -A app.celery_app worker -n historical@%h -Q historical_hydrate --concurrency=2 --loglevel=INFO
```

Mettis is scheduled only through this evidence pipeline. It is intentionally not
also run by the generic market/macro scheduler, which prevents duplicate ingestion
paths with different entity-linking and story-deduplication behavior.

The bounded Pass 4 official-source canary is disabled by default. Its `.venv`
rollout, hard budgets, included source matrix, smoke test, and live status command
are documented in [Global Evidence Pass 4: official-source canary](global-evidence-pass4-official.md).

`docker compose up -d` now starts these pools and their dedicated scheduler. Phase 2
workers do not consume evidence queues. Live messages use Redis priority `0`;
historical hydration uses priority `8`, concurrency two, and a separate queue. Every
worker mounts the same `SOURCE_ARTIFACT_ROOT` because temporary bodies move between
stages through `.evidence-spool`; Redis messages contain IDs only. Postgres leases and
candidate state reconstruct lost work after broker or worker failure.

## Frontend

```bash
cd apps/web
npm install
npm run generate:api
npm run typecheck
npm test
npm run build
npm run dev
```

`generate:api` expects the API at `http://localhost:8000` and checks `lib/generated/api.d.ts` into the repository. Main portfolio routes are `overview`, `build`, `quant`, `risk`, `scenarios`, `research`, `activity`, and `ips`; legacy `stress` and `settings` wrappers remain compatible.

Browser requests default to the same-origin `/api` path. Next.js proxies that path to
`API_INTERNAL_BASE_URL` (default `http://127.0.0.1:8000`), so an HTTPS development
tunnel only needs to expose the frontend:

```bash
cd apps/api
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

cd ../web
npm run dev -- --hostname 0.0.0.0

cloudflared tunnel --url http://localhost:3000
```

Do not set `NEXT_PUBLIC_API_BASE_URL=http://localhost:8000` for a remote preview: the
remote browser would try its own localhost and HTTPS pages may block the HTTP request.

## Verification

```bash
cd apps/api
.venv/bin/python -m pytest -q
DATABASE_URL=sqlite:////tmp/psx-migration.sqlite alembic upgrade head

cd ../web
npm run typecheck
npm test
npm run build
```

Provider parser tests use bounded fixtures and never hit live services. Live contract smoke tests are opt-in and should remain low-rate. See [migrations](migrations.md) for populated-legacy and downgrade checks.

The API-level pytest bootstrap forces an in-memory SQLite database, test bcrypt cost, disabled demo access, mock market mode, and disabled scheduled ingestion before the application package is imported. A developer `.env` therefore cannot silently redirect the test suite to local Postgres or enable source traffic. Global Evidence Pass 0 contains contracts and schema only; it has no live smoke test or provider setup command.

## Documents and RAG

```bash
cd apps/api
python -m app.jobs.ingest_document --file ./sample.pdf --symbol MEBL --type annual_report
python -m app.jobs.test_retrieval --query "deposit growth" --symbol MEBL
```

For production semantic retrieval, set `EMBEDDING_BACKEND=sentence_transformers`, install requirements, then run `python -m app.jobs.reindex_rag`. PostgreSQL stores 384-dimensional vectors with an indexed cosine search; SQLite stores vectors as JSON and scans only for tests/local use. Private uploads must be queried through their owner/portfolio scope.

## Event intelligence

After Phase 5 evidence is indexed, apply the current migration and normalize retained
announcements/news in bounded batches:

```bash
cd apps/api
alembic upgrade head
python -m app.jobs.normalize_events --rebuild --confirm-rebuild --all --limit 500
```

The command processes bounded batches until `scanned` is zero. New evidence processed by the background
evidence-index worker is normalized automatically. See `docs/event-intelligence.md` for
the event contract, deterministic boundaries, and read APIs.

## Safety assumptions

No broker password storage, browser automation, or trade placement exists. Rebalance output is only a proposal. Market prices and exact portfolio values come from database queries, while document retrieval supplies narrative evidence only.
