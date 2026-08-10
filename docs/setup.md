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

Seed deterministic development market data:

```bash
python -m app.seed.demo
```

Run the API and scheduler:

```bash
uvicorn app.main:app --reload
python -m app.jobs.scheduler --once
python -m app.jobs.scheduler
```

`MARKET_DATA_MODE=mock` is development-only. `dps` uses the verified direct DPS adapter; `auto` tries DPS and uses Yahoo only as a labeled fallback. NCCPL remains a manual CSV import because ordinary retrieval is blocked; no anti-bot bypass is implemented.

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

`generate:api` expects the API at `NEXT_PUBLIC_API_BASE_URL`/`http://localhost:8000` and checks `lib/generated/api.d.ts` into the repository. Main routes are `/dashboard`, `/portfolios`, `/portfolios/[id]/*`, `/markets`, `/research`, `/companies/[symbol]`, `/documents`, `/assistant`, and `/settings`.

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

PostgreSQL stores 384-dimensional vectors with an indexed cosine search; SQLite stores the same deterministic vectors as JSON and scans only for tests/local use. Private uploads must be queried through their owner/portfolio scope.

## Safety assumptions

No broker password storage, browser automation, or trade placement exists. Rebalance output is only a proposal. Market prices and exact portfolio values come from database queries, while document retrieval supplies narrative evidence only.
