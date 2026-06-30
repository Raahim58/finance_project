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
