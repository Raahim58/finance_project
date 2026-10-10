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

Start PostgreSQL and Redis, then migrate:

```bash
cd ../..
docker compose up -d
cd apps/api
alembic upgrade head
```

SQLite works without Docker:

```bash
DATABASE_URL=sqlite+pysqlite:///./psx_ai_local.db alembic upgrade head
```

See [migration baseline and transition](../apps/api/alembic/README.md) for populated-legacy and downgrade checks.

Local tokenizer assets (Docker installs them at image build; without them a conservative counting fallback is used):

```bash
.venv/bin/python scripts/setup_glm_tokenizer.py
```

### Demo data

Seeds the demo investor state (user, ledger-backed holdings and cash, profile, confirmed IPS, target allocation, monitoring preferences). It creates no market prices, macro data, reports, facts or events; run live ingestion afterwards.

```bash
DEMO_USER_PASSWORD='choose-a-local-password' python -m app.seed.demo
```

Login: `portfolio.manager@example.com`. The command is idempotent and never seeds an LLM key. `--with-mock-world` adds deterministic mock market data; use it only for isolated offline development, never in a live-data database.

### Run the API and ingestion

```bash
uvicorn app.main:app --reload
python -m app.jobs.pipeline_scheduler
celery -A app.celery_app worker -n pipeline-parse@%h -Q pipeline_parse --concurrency=1 --loglevel=INFO
```

The stage-to-queue map is in [Pipeline restoration](PIPELINE_RESTORATION.md); `compose.oracle.yml` is the reference deployment. Macro ingestion has its own queue and scheduler:

```bash
celery -A app.celery_app worker -P threads -n macro@%h -Q macro --concurrency=4 --loglevel=INFO
MACRO_INGESTION_ENABLED=true python -u -m app.jobs.macro_scheduler
python -m app.jobs.macro_status   # configured series, provider ladders, coverage
```

`macro_backfill` is the explicit bounded recovery tool. Compose workers and schedulers are opt-in profiles: `docker compose up -d` starts only PostgreSQL and Redis.

### Data assumptions

- `MARKET_DATA_MODE=mock` is development-only. `dps` uses the direct DPS adapter. A failed live refresh keeps prior observed rows and records staleness; it never generates mock replacements. Live modes exclude mock rows from prices, screens, valuation and quant inputs.
- The live universe is synced from observed DPS symbols; there is no configured stock list.
- DPS coverage uses the observed ordinary-equity universe as its denominator; a response missing any symbol is recorded as `partial`. DPS company-page facts are secondary fundamentals; facts extracted from official filings take precedence for the same metric and period.
- NCCPL remains a manual CSV import. No anti-bot bypass exists.
- History and report work is recorded in the `ingestion_stage_runs` outbox and dispatched by `pipeline-scheduler`, so it survives a Redis loss.
- Set `EMBEDDING_BACKEND=sentence_transformers` for production semantic retrieval (384-dim pgvector, cosine). SQLite stores JSON vectors for tests only. Private uploads are always queried by owner/portfolio scope.
- Assistant runs are owned by the API process and persisted in PostgreSQL (no Assistant worker). See [Assistant tools](mcp-tools.md) for tool bounds.
- No broker password storage, browser automation or trade placement exists. Rebalance output is a proposal only.

## Frontend

```bash
cd apps/web
npm install
npm run generate:api   # needs the API on http://localhost:8000; writes lib/generated/api.d.ts
npm run dev
```

Browser requests use the same-origin `/api` path, which Next.js proxies to `API_INTERNAL_BASE_URL` (default `http://127.0.0.1:8000`). For a remote preview, expose only the frontend (e.g. `cloudflared tunnel --url http://localhost:3000`) and do not set `NEXT_PUBLIC_API_BASE_URL=http://localhost:8000`.

To use Oracle data from a local API/web, see the remote block in `.env.example` and [Oracle deployment](oracle-deployment.md).

## Verification

```bash
cd apps/api && .venv/bin/python -m pytest -q
cd ../web && npm run typecheck && npm test && npm run build
```

The pytest bootstrap forces in-memory SQLite, mock market mode, disabled demo access and disabled scheduled ingestion before the app imports, so a developer `.env` cannot redirect tests to Postgres or enable source traffic. Parser tests use bounded fixtures; live smoke tests are opt-in and low-rate.
