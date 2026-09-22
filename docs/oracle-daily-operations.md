# Oracle Daily Operations

Use this guide after the initial Oracle migration is complete. PostgreSQL,
Redis, MinIO, the hosted API, and the hosted web application live on Oracle.
The Mac no longer contains the project database or source artifacts.

## Important: do not recreate local data volumes

Do not run this command on the Mac:

```bash
docker compose up -d
```

The default local Compose file would create new, empty PostgreSQL and Redis
volumes. Manage the deployed services on Oracle instead, using the commands
below.

## Start or check the Oracle application

Run this from the Mac:

```bash
ssh -i ~/.ssh/oracle_psx ubuntu@141.145.146.120 \
  'cd ~/finance_project && docker compose -f compose.oracle.yml up -d'
```

This uses the images already built on Oracle and does not rebuild them. Add
`--build` only after deploying code or dependency changes that require new
images.

Check service status:

```bash
ssh -i ~/.ssh/oracle_psx ubuntu@141.145.146.120 \
  'cd ~/finance_project && docker compose -f compose.oracle.yml ps'
```

The normal always-on services are:

- PostgreSQL
- Redis
- MinIO
- FastAPI
- Next.js

Workers and schedulers should not appear unless they were started manually.

## Open the SSH tunnel

Run this in a dedicated Mac terminal and leave it open:

```bash
ssh -i ~/.ssh/oracle_psx -N \
  -L 13000:127.0.0.1:3000 \
  -L 15432:127.0.0.1:5432 \
  -L 16379:127.0.0.1:6379 \
  -L 19000:127.0.0.1:9000 \
  ubuntu@141.145.146.120
```

The forwarded services are:

| Mac address | Oracle service |
|---|---|
| `http://localhost:13000` | Hosted Next.js application |
| `127.0.0.1:15432` | PostgreSQL |
| `127.0.0.1:16379` | Redis |
| `http://127.0.0.1:19000` | MinIO S3 API |

The tunnel produces no normal terminal output. Stop it with `Ctrl+C`.

## Use the hosted application

After opening the tunnel, visit:

```text
http://localhost:13000
```

No application process needs to run on the Mac for this mode.

## Run current code locally with Oracle data

Open the SSH tunnel first. The local API configuration is stored in
`apps/api/.env.remote` and points to the remote development database,
Oracle Redis databases 2 and 3, and Oracle MinIO.

Start the local API:

```bash
cd /Users/Raahim/Documents/LUMS/Junior/summer_semester/Tintash/finance_project/apps/api

set -a
source .env.remote
set +a

uvicorn app.main:app --reload \
  --host 127.0.0.1 \
  --port 8000
```

In another terminal, start the local frontend:

```bash
cd /Users/Raahim/Documents/LUMS/Junior/summer_semester/Tintash/finance_project/apps/web
API_INTERNAL_BASE_URL=http://127.0.0.1:8000 npm run dev
```

Open:

```text
http://localhost:3000
```

This gives local hot reload while all persistent database and artifact data
remains on Oracle.

## Run a one-time market ingestion

From the Mac:

```bash
ssh -i ~/.ssh/oracle_psx ubuntu@141.145.146.120 \
  'cd ~/finance_project && ./ops/ingestion run market'
```

This is a bounded run and does not leave a continuous scheduler running.

## Run Phase 2 ingestion

Start the Phase 2 worker consumers:

```bash
ssh -i ~/.ssh/oracle_psx ubuntu@141.145.146.120 \
  'cd ~/finance_project && ./ops/ingestion start phase2'
```

If continuous queue production is wanted, explicitly start the scheduler:

```bash
ssh -i ~/.ssh/oracle_psx ubuntu@141.145.146.120 \
  'cd ~/finance_project && docker compose -f compose.oracle.yml --profile scheduling up -d phase2-scheduler'
```

When finished, stop the scheduler first so it cannot publish more work:

```bash
ssh -i ~/.ssh/oracle_psx ubuntu@141.145.146.120 \
  'cd ~/finance_project && docker compose -f compose.oracle.yml --profile scheduling stop phase2-scheduler'
```

After the workers have drained their queues, stop them:

```bash
ssh -i ~/.ssh/oracle_psx ubuntu@141.145.146.120 \
  'cd ~/finance_project && ./ops/ingestion stop phase2'
```

Do not purge Redis queues merely to stop ingestion.

## Run macro or evidence workers

Connect to Oracle:

```bash
ssh -i ~/.ssh/oracle_psx ubuntu@141.145.146.120
cd ~/finance_project
```

Then use the required commands:

```bash
./ops/ingestion start macro
./ops/ingestion start evidence
./ops/ingestion status
./ops/ingestion stop macro
./ops/ingestion stop evidence
./ops/ingestion stop all
```

Starting a worker group starts consumers only. Any continuous scheduler remains
a separate explicit action under the `scheduling` Compose profile.

## Inspect logs

Core application logs:

```bash
docker compose -f compose.oracle.yml logs --tail=200 api web postgres redis minio
```

Follow a particular worker:

```bash
docker compose -f compose.oracle.yml --profile ingestion \
  logs --tail=200 --follow worker-dps-history
```

Press `Ctrl+C` to stop following logs; this does not stop the service.

## Stop or restart Oracle services

Restart only the API and web application:

```bash
docker compose -f compose.oracle.yml restart api web
```

Stop every manually started worker and scheduler:

```bash
./ops/ingestion stop all
```

Stop the core application without deleting Oracle data:

```bash
docker compose -f compose.oracle.yml stop
```

Start it again:

```bash
docker compose -f compose.oracle.yml up -d
```

Do not run `docker compose down -v` or manually remove the Oracle PostgreSQL,
Redis, or MinIO storage directories.

## Quick health check

On Oracle:

```bash
curl --fail http://127.0.0.1:3000/api/health
curl --fail http://127.0.0.1:3000/api/ready
```

The readiness response should report `ok` for the database, Redis, and artifact
storage.

## Related deployment documentation

For migration, restoration, backup, and initial provisioning details, see
[Private Oracle deployment and remote-data development](oracle-deployment.md).
