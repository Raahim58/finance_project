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

Run the API and scheduler:

```bash
uvicorn app.main:app --reload
python -m app.jobs.scheduler --once
python -m app.jobs.scheduler
python -m app.jobs.backfill_market_history --provider dps --symbols MEBL,SYS --start 2021-01-01 --end 2026-08-10
```

The current default universe uses `ENGROH`; `ENGRO` is a distinct delisted
historical identity and is not silently remapped for valuation.

`MARKET_DATA_MODE=mock` is development-only. `dps` uses the verified direct DPS adapter; `auto` tries DPS and uses Yahoo only as a labeled real-data fallback. A failed live refresh retains prior observed rows and records failure/staleness; it never generates mock replacements. NCCPL remains a manual CSV import because ordinary retrieval is blocked; no anti-bot bypass is implemented.

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
DATABASE_URL=sqlite:////tmp/psx-tests.sqlite pytest -q
DATABASE_URL=sqlite:////tmp/psx-migration.sqlite alembic upgrade head

cd ../web
npm run typecheck
npm test
npm run build
```

Provider parser tests use bounded fixtures and never hit live services. Live contract smoke tests are opt-in and should remain low-rate. See [migrations](migrations.md) for populated-legacy and downgrade checks.

## Documents and RAG

```bash
cd apps/api
python -m app.jobs.ingest_document --file ./sample.pdf --symbol MEBL --type annual_report
python -m app.jobs.test_retrieval --query "deposit growth" --symbol MEBL
```

For production semantic retrieval, set `EMBEDDING_BACKEND=sentence_transformers`, install requirements, then run `python -m app.jobs.reindex_rag`. PostgreSQL stores 384-dimensional vectors with an indexed cosine search; SQLite stores vectors as JSON and scans only for tests/local use. Private uploads must be queried through their owner/portfolio scope.

## Safety assumptions

No broker password storage, browser automation, or trade placement exists. Rebalance output is only a proposal. Market prices and exact portfolio values come from database queries, while document retrieval supplies narrative evidence only.
