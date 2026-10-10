# Private Oracle deployment and remote-data development

This deployment keeps PostgreSQL, Redis, immutable source artifacts, the API,
and the web application on one Oracle VM. Nothing is publicly exposed: every
published port binds to Oracle loopback and is reached from the Mac over SSH.
Ingestion workers and schedulers are disabled unless an operator starts them.

## 1. Provision the VM and disk

Create an Ubuntu Ampere A1 VM and attach enough block storage for the database,
artifacts, backups, and growth. Keep only TCP 22 open in the Oracle
network security rules. On the VM, format and mount the data volume at
`/srv/psx`, then create the owned directories:

```bash
sudo mkdir -p /srv/psx/{postgres,redis,minio,import,backups}
sudo chown -R "$USER":"$USER" /srv/psx
sudo chmod 700 /srv/psx/{postgres,redis,minio,import,backups}
```

Add the volume to `/etc/fstab`, enable a 4 GiB swap file, install Docker Engine
and its Compose plugin, clone this repository, and verify `docker compose
version`. Those host-level actions require sudo and are intentionally not
automated by this repository.

## 2. Configure secrets and start storage

On Oracle, from the repository root:

```bash
cp .env.oracle.example .env.oracle
chmod 600 .env.oracle
python3 -c 'import secrets; print(secrets.token_urlsafe(48))'
```

Generate separate strong values for the PostgreSQL password, JWT secret, and
MinIO credentials. If the existing canonical database contains saved LLM keys,
copy its current `ENCRYPTION_KEY` securely into `.env.oracle`; changing it would
make those encrypted rows unreadable. Generate a new Fernet key only if there
are no saved keys to preserve. The development clone gets a different key after
its `llm_api_keys` table is cleared. URL-encode special characters in the
password embedded in `DATABASE_URL`. Never commit `.env.oracle`.

Start only the durable dependencies first:

```bash
docker compose -f compose.oracle.yml up -d postgres redis minio minio-init
docker compose -f compose.oracle.yml ps
```

The initialization SQL creates an empty `psx_ai_dev` database only on the first
PostgreSQL initialization. It never overwrites an existing database.

## 3. Create the development database

The remote-data workflow uses a separate `psx_ai_dev` database. Create it from
canonical while ingestion and canonical writes are stopped, and drop the saved
LLM keys from the clone:

```bash
docker compose -f compose.oracle.yml exec -T postgres sh -c \
  'pg_dump -U "$POSTGRES_USER" -Fc psx_ai > /tmp/psx_ai_dev.dump && dropdb -U "$POSTGRES_USER" --if-exists psx_ai_dev && createdb -U "$POSTGRES_USER" -O "$POSTGRES_USER" psx_ai_dev && pg_restore -U "$POSTGRES_USER" -d psx_ai_dev --no-owner /tmp/psx_ai_dev.dump && rm /tmp/psx_ai_dev.dump'
docker compose -f compose.oracle.yml exec -T postgres \
  psql -U psx -d psx_ai_dev -c 'TRUNCATE TABLE llm_api_keys;'
```

The snapshot does not update afterward.

## 4. Start and verify the application

```bash
docker compose -f compose.oracle.yml up -d --build
docker compose -f compose.oracle.yml ps
curl --fail http://127.0.0.1:3000/api/health
curl --fail http://127.0.0.1:3000/api/ready
```

Plain `up -d` starts only PostgreSQL, Redis, MinIO, API, and web. It does not
start any worker or scheduler. Reboot behavior is the same: core services use
`unless-stopped`; ingestion services use `restart: no`.

## 5. Use all remote data from localhost

On the Mac, create one tunnel and leave it running:

```bash
ssh -N \
  -L 13000:127.0.0.1:3000 \
  -L 15432:127.0.0.1:5432 \
  -L 16379:127.0.0.1:6379 \
  -L 19000:127.0.0.1:9000 \
  ubuntu@ORACLE_HOST
```

For the remote deployed app, open `http://localhost:13000`. To run current code
locally with hot reload but use no local persistent data:

```bash
# In apps/api/.env (copied from .env.example), uncomment the "Remote data
# through the Oracle tunnel" block and fill in the credentials, then:
cd apps/api
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

# In another terminal:
cd apps/web
API_INTERNAL_BASE_URL=http://127.0.0.1:8000 npm run dev
```

The API uses Oracle `psx_ai_dev`, Oracle Redis databases 2/3, and Oracle MinIO.
Unit tests remain isolated in memory/temp directories. Keep ingestion flags
false in that block; canonical ingestion should run on Oracle.

## 6. Run ingestion only when wanted

From the Oracle repository checkout:

```bash
./ops/ingestion status
./ops/ingestion run market
./ops/ingestion start macro
./ops/ingestion start pipeline
./ops/ingestion stop all
```

`start` launches consumers only. A continuous producer remains a separate,
explicit action, for example:

```bash
docker compose -f compose.oracle.yml --profile pipeline up -d pipeline-scheduler
docker compose -f compose.oracle.yml --profile pipeline stop pipeline-scheduler
```

Start the matching workers before a scheduler. Stop the scheduler first, allow
workers to drain, then stop workers. Never purge Redis queues merely to stop a
run; PostgreSQL coverage/lease records are the durable control plane.

## Backups

Schedule an encrypted off-VM copy of nightly PostgreSQL custom-format dumps and enable OCI block-volume backups
for `/srv/psx`. Retain at least two known-good recovery points. A backup is not
accepted until a dump has restored successfully into a disposable database and
representative MinIO objects pass their SHA-256 checks.


## 7. Deploying while ingestion runs

Deploys do **not** require stopping workers or schedulers. `.github/workflows/deploy-oracle.yml` checks out the commit and runs `ops/oracle-deploy`:

1. Builds `api` and `web` (running containers are untouched).
2. `python -m app.jobs.check_migrations_additive` refuses pending migrations that drop/rename/alter anything, because old-code workers keep running during the schema change. Override only after coordinating: `ALLOW_BREAKING_MIGRATION=1`. Use expand/contract migrations instead.
3. `alembic upgrade head`, redeploys `api web research-worker`, waits for `/api/ready`.
4. Rolls each running worker/scheduler onto the new image **one at a time** (graceful stop up to `DEPLOY_DRAIN_SECONDS`, default 180, then `up -d --no-deps`), consumers before schedulers. Redis queues are never purged and other queues keep consuming; leases in PostgreSQL recover any cut-off task. `DEPLOY_RESTART_WORKERS=0` skips this step, leaving workers on the old image until restarted.

Workers that were not running before the deploy are not started. Assumption: the migration check is a source scan, not a proof of compatibility; reviewing migrations still matters. Remaining unverified: behaviour on the real host (the script is tested against a stubbed `docker` only).
