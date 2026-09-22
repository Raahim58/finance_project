# Private Oracle deployment and remote-data development

This deployment keeps PostgreSQL, Redis, immutable source artifacts, the API,
and the web application on one Oracle VM. Nothing is publicly exposed: every
published port binds to Oracle loopback and is reached from the Mac over SSH.
Ingestion workers and schedulers are disabled unless an operator starts them.

## 1. Provision the VM and disk

Create an Ubuntu Ampere A1 VM and attach enough block storage for the database,
artifacts, imports, backups, and growth. Keep only TCP 22 open in the Oracle
network security rules. On the VM, format and mount the data volume at
`/srv/psx`, then create the owned directories:

```bash
sudo mkdir -p /srv/psx/{postgres,redis,minio,import,backups}
sudo chown -R "$USER":"$USER" /srv/psx
sudo chmod 700 /srv/psx/{postgres,redis,minio,backups}
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

## 3. Transfer the existing database and artifacts

Pause local ingestion and anything that writes to PostgreSQL. Substitute the
Oracle SSH host below. Stream a compressed database dump without leaving a
second dump on the Mac:

```bash
pg_dump -Fc 'postgresql://psx:LOCAL_PASSWORD@127.0.0.1:5433/psx_ai' \
  | ssh ubuntu@ORACLE_HOST 'cat > /srv/psx/import/psx_ai.dump'
```

Copy the host artifact tree resumably:

```bash
rsync -a --info=progress2 --partial \
  apps/api/data/artifacts/ \
  ubuntu@ORACLE_HOST:/srv/psx/import/host-artifacts/
```

Find the existing Docker artifact volume using `docker volume ls`. If it
contains files not present in the host tree, stream it without creating a local
archive (replace `SOURCE_VOLUME` with the exact inspected name):

```bash
docker run --rm -v SOURCE_VOLUME:/from:ro alpine \
  tar -C /from -cf - . \
  | ssh ubuntu@ORACLE_HOST 'mkdir -p /srv/psx/import/volume-artifacts && tar -C /srv/psx/import/volume-artifacts -xf -'
```

On Oracle, restore canonical PostgreSQL. The following clears only the newly
created Oracle `psx_ai` database, not the Mac database:

```bash
docker compose -f compose.oracle.yml exec -T postgres \
  pg_restore -U psx -d psx_ai --clean --if-exists --no-owner /dev/stdin \
  < /srv/psx/import/psx_ai.dump
docker compose -f compose.oracle.yml run --rm api alembic upgrade head
```

Convert legacy absolute filesystem paths to private content-addressed MinIO
URIs. First run a read-only inventory; then apply; then independently verify:

```bash
docker compose -f compose.oracle.yml run --rm api \
  python -m app.jobs.migrate_artifacts \
  --path-map '/Users/Raahim/Documents/LUMS/Junior/summer_semester/Tintash/finance_project/apps/api/data/artifacts=/import/host-artifacts' \
  --path-map '/data/artifacts=/import/volume-artifacts' \
  --scan-root /import/host-artifacts --scan-root /import/volume-artifacts

docker compose -f compose.oracle.yml run --rm api \
  python -m app.jobs.migrate_artifacts --apply \
  --path-map '/Users/Raahim/Documents/LUMS/Junior/summer_semester/Tintash/finance_project/apps/api/data/artifacts=/import/host-artifacts' \
  --path-map '/data/artifacts=/import/volume-artifacts' \
  --scan-root /import/host-artifacts --scan-root /import/volume-artifacts \
  --manifest /backups/artifact-migration-manifest.json

docker compose -f compose.oracle.yml run --rm api \
  python -m app.jobs.migrate_artifacts --verify \
  --scan-root /import/host-artifacts --scan-root /import/volume-artifacts
```

The apply command hashes the source, compares it with `source_artifacts.sha256`,
uploads to `sha256/<first-two>/<full-hash>`, reads the object back, verifies it,
and only then commits that row's `s3://` URI. It is safe to rerun. A missing or
mismatched source exits non-zero and is never silently accepted.
`--scan-root` also uploads physical files with no database reference, but does
not invent provenance rows for them.

## 4. Create the initial development snapshot

The development database is remote too. Create it from canonical only while
canonical writes and all ingestion are stopped:

```bash
docker compose -f compose.oracle.yml exec -T postgres sh -c \
  'pg_dump -U "$POSTGRES_USER" -Fc psx_ai > /tmp/psx_ai_dev.dump && dropdb -U "$POSTGRES_USER" --if-exists psx_ai_dev && createdb -U "$POSTGRES_USER" -O "$POSTGRES_USER" psx_ai_dev && pg_restore -U "$POSTGRES_USER" -d psx_ai_dev --no-owner /tmp/psx_ai_dev.dump && rm /tmp/psx_ai_dev.dump'
docker compose -f compose.oracle.yml exec -T postgres \
  psql -U psx -d psx_ai_dev -c 'TRUNCATE TABLE llm_api_keys;'
```

This is the initial straightforward snapshot selected for phase one. It does
not automatically change afterward. The manual logical-replication catch-up
command belongs to phase two, so local development changes cannot accidentally
be overwritten during this cutover.

## 5. Start and verify the application

```bash
docker compose -f compose.oracle.yml up -d --build
docker compose -f compose.oracle.yml ps
curl --fail http://127.0.0.1:3000/api/health
curl --fail http://127.0.0.1:3000/api/ready
```

Plain `up -d` starts only PostgreSQL, Redis, MinIO, API, and web. It does not
start any worker or scheduler. Reboot behavior is the same: core services use
`unless-stopped`; ingestion services use `restart: no`.

## 6. Use all remote data from localhost

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
cp .env.remote.example apps/api/.env.remote
# Fill credentials, then:
cd apps/api
set -a; source .env.remote; set +a
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

# In another terminal:
cd apps/web
API_INTERNAL_BASE_URL=http://127.0.0.1:8000 npm run dev
```

The API uses Oracle `psx_ai_dev`, Oracle Redis databases 2/3, and Oracle MinIO.
Unit tests remain isolated in memory/temp directories. Keep ingestion flags
false in `.env.remote`; canonical ingestion should run on Oracle.

## 7. Run ingestion only when wanted

From the Oracle repository checkout:

```bash
./ops/ingestion status
./ops/ingestion run market
./ops/ingestion start phase2
./ops/ingestion start macro
./ops/ingestion start evidence
./ops/ingestion stop all
```

`start` launches consumers only. A continuous producer remains a separate,
explicit action, for example:

```bash
docker compose -f compose.oracle.yml --profile scheduling up -d phase2-scheduler
docker compose -f compose.oracle.yml --profile scheduling stop phase2-scheduler
```

Start the matching workers before a scheduler. Stop the scheduler first, allow
workers to drain, then stop workers. Never purge Redis queues merely to stop a
run; PostgreSQL coverage/lease records are the durable control plane.

## 8. Acceptance checks before deleting Mac data

Do not delete local artifacts or Docker volumes until all of these pass:

1. `/ready` reports database, Redis, and artifact storage as `ok`.
2. The artifact verifier exits zero and reports no missing/hash-mismatch rows.
3. Key table counts match between the old and canonical Oracle databases.
4. A document/PDF can be opened or parsed through the local API via MinIO.
5. The local API runs with local PostgreSQL stopped.
6. `docker compose -f compose.oracle.yml ps` shows no ingestion services after a reboot.
7. A PostgreSQL backup has been restored into a disposable database at least once.

Only then remove the exact inspected local artifact directory and exact named
Docker volumes. Keep the Oracle import copy until a second backup is confirmed;
it is the rollback source for the initial migration.

## Backups

Schedule an encrypted off-VM copy of nightly PostgreSQL custom-format dumps and
`/backups/artifact-migration-manifest.json`, and enable OCI block-volume backups
for `/srv/psx`. Retain at least two known-good recovery points. A backup is not
accepted until a dump has restored successfully into a disposable database and
representative MinIO objects pass their SHA-256 checks.
