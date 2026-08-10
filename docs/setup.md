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

Copy the generated Fernet key into `ENCRYPTION_KEY`.

Set market ingestion mode in `.env`:

```bash
MARKET_DATA_MODE=auto
MARKET_DATA_REFRESH_SECONDS=300
SOURCE_ARTIFACT_ROOT=./data/artifacts
```

Supported market modes:

- `mock` for local development and deterministic tests
- `dps` for verified direct PSX DPS ingestion
- `yahoo` for direct Yahoo Finance ingestion using `.KA` symbol mapping
- `auto` to try DPS first and fall back to Yahoo if needed
- `psxdata` for temporary compatibility/comparison only

Run tests:

```bash
cd ../..
apps/api/.venv/bin/python -m pytest
```

Run API locally:

```bash
cd apps/api
source .venv/bin/activate
uvicorn app.main:app --reload
```

Seed Phase 2 mock market data:

```bash
cd apps/api
source .venv/bin/activate
python -m app.jobs.ingest_psx_mock --days 365
```

Run the market scheduler once:

```bash
cd apps/api
source .venv/bin/activate
python -m app.jobs.scheduler --once
```

Run the market scheduler continuously:

```bash
cd apps/api
source .venv/bin/activate
python -m app.jobs.scheduler
```

## Database

Start PostgreSQL and Redis:

```bash
docker compose up -d
```

Run migrations:

```bash
cd apps/api
source .venv/bin/activate
alembic upgrade head
```

The backend defaults to SQLite for local skeleton runs if `DATABASE_URL` is not set.

Recompute Phase 2 derived stats if needed:

```bash
cd apps/api
source .venv/bin/activate
python -m app.jobs.compute_market_stats
```

`MARKET_DATA_MODE=mock` is only for local development. For current data, prefer `dps` or `auto`. Raw artifacts are content-addressed under `SOURCE_ARTIFACT_ROOT`. `vendor` remains disabled until a real contract is verified.

Migration and verification commands:

```bash
cd apps/api
alembic upgrade head
pytest -q app/tests
```

The four workstation migrations deliberately persist audit/reproduction-sensitive optimizer, scenario, and recommendation state. Routine dashboard analytics remain calculated/cached.

Ingest a Phase 4 local text/Markdown document:

```bash
cd apps/api
source .venv/bin/activate
python -m app.jobs.ingest_document --file ./sample.txt --symbol MEBL --type annual_report
```

Run a Phase 4 retrieval smoke test:

```bash
cd apps/api
source .venv/bin/activate
python -m app.jobs.test_retrieval --query "deposit growth" --symbol MEBL
```

PDF parsing is supported only when the optional `pypdf` package is installed in the backend environment.

## Frontend

```bash
cd apps/web
npm install
npm run dev
```

Open `http://localhost:3000`.

Phase 2 pages:

- `http://localhost:3000/market`
- `http://localhost:3000/companies/MEBL`

Phase 3 page:

- `http://localhost:3000/portfolio`

Create an account first, then add a portfolio and holdings. Symbols must exist in the market company table, so seed Phase 2 mock market data before using the portfolio page.
Manual portfolio entry is the MVP fallback. Future real portfolio sync should go through official broker APIs or approved partnerships.

Phase 4 page:

- `http://localhost:3000/documents`

Create an account first to upload documents. Search is read-only and returns chunks with citation metadata.
