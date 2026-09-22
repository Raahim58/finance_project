# Oracle Migration Handoff / Full Resume Context

**Purpose:** This file is a complete handoff for resuming the Oracle Cloud migration in a new ChatGPT conversation without re-explaining the setup.  
**Current status at handoff:** Phases **0–19 are complete**, **Phase 20 is in progress**, and **Phases 21–37 remain**.  
**Current active task:** transferring the local `apps/api/data/artifacts/` directory (~12 GB) from the Mac to Oracle using `rsync`.

---

## 1. Critical resume instructions

If this file is being used in a new chat:

1. **Do not redo the Oracle account, VM, VCN, storage, Docker, repo, env, build, database dump, or database validation steps. They are already complete.**
2. Continue from **Phase 20**, specifically the host-artifact `rsync` transfer.
3. Before advancing to Phase 21, determine whether the current `rsync` command finished. If it finished, verify:
   ```bash
   du -sh /srv/psx/import/host-artifacts
   ```
   on Oracle.
4. Do **not** delete any local Mac database volumes or artifact data until the final verification and backup stages.
5. Local ingestion workers/schedulers are intentionally stopped and removed. Keep them stopped until the migration is complete.
6. The PostgreSQL dump on Oracle has already been validated successfully. **Do not redo the dump unless there is later evidence of corruption.**
7. Never ask for or print the real values of `POSTGRES_PASSWORD`, `JWT_SECRET_KEY`, `MINIO_ROOT_PASSWORD`, `ENCRYPTION_KEY`, etc. They are already configured.
8. The working Oracle SSH private-key path on the Mac is:
   ```text
   ~/.ssh/oracle_psx
   ```
9. Oracle public IPv4:
   ```text
   141.145.146.120
   ```
10. Oracle SSH login:
   ```bash
   ssh -i ~/.ssh/oracle_psx ubuntu@141.145.146.120
   ```

---

# 2. Original migration plan: 38 phases (0–37)

| Phase | Description | Status |
|---:|---|---|
| 0 | Create Oracle Cloud account | ✅ DONE |
| 1 | Put deployment code in Git / verify branch | ✅ DONE |
| 2 | Create SSH key | ✅ DONE |
| 3 | Create Oracle VM | ✅ DONE |
| 4 | Record public IPv4 | ✅ DONE |
| 5 | Test SSH | ✅ DONE |
| 6 | Create 150 GB block volume | ✅ DONE |
| 7 | Identify new disk | ✅ DONE |
| 8 | Format and mount data disk | ✅ DONE |
| 9 | Persist mount via `/etc/fstab` | ✅ DONE |
| 10 | Create `/srv/psx` application directories | ✅ DONE |
| 11 | Create 4 GB swap | ✅ DONE |
| 12 | Install Docker | ✅ DONE |
| 13 | Reconnect and test Docker without `sudo` | ✅ DONE |
| 14 | Clone application repo | ✅ DONE |
| 15 | Create/configure `.env.oracle` | ✅ DONE |
| 16 | Build API + web Docker images | ✅ DONE |
| 17 | Start only PostgreSQL/Redis/MinIO | ✅ DONE |
| 18 | Stop local ingestion/scheduling | ✅ DONE |
| 19 | Stream PostgreSQL dump to Oracle + validate | ✅ DONE |
| 20 | Transfer host artifact directory | 🔄 **IN PROGRESS** |
| 21 | Transfer old Docker `source_artifacts` volume | ⏳ NOT STARTED |
| 22 | Restore PostgreSQL on Oracle + Alembic | ⏳ NOT STARTED |
| 23 | Artifact migration read-only inventory | ⏳ NOT STARTED |
| 24 | Apply artifact migration into MinIO | ⏳ NOT STARTED |
| 25 | Verify artifact migration | ⏳ NOT STARTED |
| 26 | Create `psx_ai_dev` DB and clear dev LLM keys | ⏳ NOT STARTED |
| 27 | Start hosted application | ⏳ NOT STARTED |
| 28 | Create SSH tunnel from Mac | ⏳ NOT STARTED |
| 29 | Configure local development against Oracle | ⏳ NOT STARTED |
| 30 | Run local API against Oracle services | ⏳ NOT STARTED |
| 31 | Run local web app | ⏳ NOT STARTED |
| 32 | Understand hosted vs local-development modes | ⏳ Informational |
| 33 | Test/manual ingestion controls | ⏳ NOT STARTED |
| 34 | Create canonical Oracle PostgreSQL backup | ⏳ NOT STARTED |
| 35 | Create OCI block-volume backup | ⏳ NOT STARTED |
| 36 | Prove local storage is unnecessary | ⏳ NOT STARTED |
| 37 | Only then optionally delete old Mac data | ⏳ NOT STARTED |

---

# 3. Oracle Cloud resource configuration

## Region / placement

Oracle region being used:

```text
ME-DUBAI-1
```

Availability domain:

```text
AD-1
usWf:ME-DUBAI-1-AD-1
```

Compartment:

```text
storage-lab (root)
```

Capacity type:

```text
On-demand
```

Fault domain:

```text
Let Oracle choose the best fault domain
```

---

## Compute instance

Instance name:

```text
psx-oracle
```

The Linux shell hostname appears as:

```text
psx
```

Typical Oracle prompt:

```text
ubuntu@psx:~$
```

Instance is running successfully.

### Image

```text
Canonical Ubuntu 24.04
Image build: 2026.09.18-0
Architecture: ARM64 / aarch64
```

`uname -m` was expected/verified as `aarch64`.

### Shape

```text
VM.Standard.A1.Flex
2 OCPUs
12 GB RAM
2 Gbps network bandwidth
```

This is the selected Ampere A1 Flex configuration.

### Instance security / management snapshot

- Instance Metadata authorization header: **Enabled**
- Shielded instance features:
  - Secure Boot: Disabled
  - Measured Boot: Disabled
  - TPM: Disabled
- Live migration: Oracle chooses best migration option
- Restart after infrastructure maintenance: Enabled
- Tags: none

Oracle Cloud Agent settings shown during review:

- Vulnerability Scanning: Disabled
- OS Management Hub Agent: Disabled
- Management Agent: Disabled
- Custom Logs Monitoring: Enabled
- Compute RDMA GPU Monitoring: Disabled
- Compute Instance Monitoring: Enabled
- Compute HPC RDMA Auto-Configuration: Disabled
- Compute HPC RDMA Authentication: Disabled
- Cloud Guard Workload Protection: Enabled
- Block Volume Management: Disabled
- Bastion: Disabled

---

# 4. Network configuration

## Public IPv4

```text
141.145.146.120
```

This is the Oracle VM public IPv4 currently used for SSH and transfers.

## VCN

Name:

```text
psx-vcn
```

VCN IPv4 CIDR:

```text
10.0.0.0/16
```

DNS hostnames were enabled when the VCN was created.

## Public subnet

Name:

```text
psx-public-subnet
```

CIDR:

```text
10.0.0.0/24
```

The VM receives:

- Private IPv4: automatically assigned
- Public IPv4: yes
- IPv6: disabled/not used
- Private DNS record: yes
- Network Security Groups: not used
- OCI chooses networking type

The exact private IPv4 address was **not recorded in this chat** because it was not needed.

## Internet gateway

Name:

```text
psx-internet-gateway
```

The gateway was created separately because the inline VM creation flow would not enable the public IPv4 control.

Gateway route-table association was intentionally left blank.

## Route rule

The default route table for `psx-vcn` has:

```text
Destination: 0.0.0.0/0
Target type: Internet Gateway
Target: psx-internet-gateway
```

The warning about enabling “Skip Source/Destination Check” for routes targeting a **Private IP** was determined to be irrelevant because this route targets an **Internet Gateway**, not a private IP.

## Security / exposed ports

Design goal:

- SSH port `22`: allowed
- Do **not** publicly expose:
  - `3000`
  - `5432`
  - `6379`
  - `8000`
  - `9000`
  - `9001`

Oracle Docker services currently bind sensitive ports to `127.0.0.1`, e.g.:

```text
MinIO:      127.0.0.1:9000-9001
PostgreSQL: 127.0.0.1:5432
Redis:      127.0.0.1:6379
```

SSH access is working, so port 22 is functioning.

---

# 5. SSH configuration

Working private key path on Mac:

```text
~/.ssh/oracle_psx
```

Oracle login user:

```text
ubuntu
```

Working command:

```bash
ssh -i ~/.ssh/oracle_psx ubuntu@141.145.146.120
```

A public `ssh-ed25519` key was uploaded to OCI during instance creation.

Do not expose or transmit the private key contents.

---

# 6. Oracle storage layout

## Boot volume

Boot volume configuration:

```text
50 GB
10 VPU/GB
Balanced
In-transit encryption: Enabled
Oracle-managed encryption key
```

Ubuntu boot device:

```text
/dev/sda
```

Observed partition layout:

```text
sda        50G            BlockVolume
├─sda1     49G ext4       /
├─sda15    99M vfat       /boot/efi
└─sda16   923M ext4       /boot
```

At one checkpoint after Docker images/storage services were created:

```text
/dev/sda1  48G total
27G used
22G available
56% used
```

The API Docker image is large, partly because the requirements include Torch / Transformers / sentence-transformers / NVIDIA-related wheels.

---

## Data block volume

OCI volume name:

```text
psx-data
```

Configuration:

```text
150 GB
Availability domain: usWf:ME-DUBAI-1-AD-1
Performance: 10 VPU/GB (Balanced)
IOPS shown by OCI: 9,000
Throughput shown by OCI: 72 MB/s
Performance based auto-tune: OFF
Detached-volume auto-tune: OFF
Reservations: OFF
Backup policy: NONE
Cross AD/region replication: OFF
Encryption: Oracle-managed keys
```

Attachment:

```text
Paravirtualized
Read/Write
```

Linux device:

```text
/dev/sdb
```

Observed before formatting:

```text
sdb   150G   no filesystem   no mount point   BlockVolume
```

It was formatted as `ext4`.

Mount point:

```text
/srv/psx
```

Observed mount:

```text
/srv/psx /dev/sdb ext4 rw,relatime,stripe=256
```

At one checkpoint:

```text
/dev/sdb 147G total
69M used
140G available
1% used
```

That free-space number was before the 12 GB artifact migration began.

### Persistent mount

`/etc/fstab` contains a UUID-based entry conceptually equivalent to:

```text
UUID=<DATA_VOLUME_UUID> /srv/psx ext4 defaults,nofail,_netdev 0 2
```

The exact `/dev/sdb` filesystem UUID was **not pasted into this chat**, so do not invent it.

If needed, retrieve it with:

```bash
sudo blkid /dev/sdb
```

Persistent mounting was tested with:

```bash
sudo umount /srv/psx
sudo mount -a
findmnt /srv/psx
```

It remounted successfully.

After editing `fstab`, this was also run:

```bash
sudo systemctl daemon-reload
```

---

# 7. `/srv/psx` directory structure and permissions

Created:

```text
/srv/psx/
├── postgres
├── redis
├── minio
├── import
├── backups
└── lost+found
```

`lost+found` is the normal ext4 filesystem directory and should be left alone.

Ownership:

```text
ubuntu:ubuntu
```

Observed permissions:

```text
/srv/psx             drwxr-xr-x
/srv/psx/backups     drwx------
/srv/psx/import      drwxr-xr-x
/srv/psx/lost+found  drwx------
/srv/psx/minio       drwx------
/srv/psx/postgres    drwx------
/srv/psx/redis       drwx------
```

Commands used:

```bash
sudo mkdir -p /srv/psx/{postgres,redis,minio,import,backups}
sudo chown -R "$USER":"$USER" /srv/psx
sudo chmod 700 /srv/psx/{postgres,redis,minio,backups}
```

---

# 8. Swap configuration

Swap file:

```text
/swapfile
```

Size:

```text
4 GB
```

Commands used:

```bash
sudo fallocate -l 4G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
sudo systemctl daemon-reload
```

`mkswap` reported swap UUID:

```text
43ae3000-187c-466f-afb0-2ba20ddc3182
```

`free -h` showed:

```text
RAM:  ~11 GiB total
Swap: 4.0 GiB total
```

`swapon --show` showed:

```text
NAME      TYPE SIZE USED PRIO
/swapfile file   4G   0B   -2
```

---

# 9. Docker installation

Docker installed from Docker’s official Ubuntu repository.

Architecture of repository/package installation:

```text
arm64
Ubuntu noble / 24.04
```

Installed packages/versions observed:

```text
docker-ce                29.8.1
docker-ce-cli            29.8.1
containerd.io            2.3.5
docker-buildx-plugin     0.37.1
docker-compose-plugin    5.5.1
docker-ce-rootless-extras 29.8.1
```

Docker service verified:

```text
Active: active (running)
```

`hello-world` ran successfully and explicitly pulled:

```text
arm64v8
```

User `ubuntu` was added to Docker group:

```bash
sudo usermod -aG docker "$USER"
```

Then the SSH session was exited and reconnected so Docker could run without `sudo`.

---

# 10. Git / project locations

## Local Mac project

```text
/Users/Raahim/Documents/LUMS/Junior/summer_semester/Tintash/finance_project
```

Typical Mac prompt:

```text
(base) Raahim@Raahims-MacBook finance_project %
```

## Oracle project

```text
/home/ubuntu/finance_project
```

Equivalent shell shortcut:

```text
~/finance_project
```

Typical prompt:

```text
ubuntu@psx:~/finance_project$
```

## GitHub repository

```text
https://github.com/Raahim58/finance_project.git
```

Current Oracle branch:

```text
main
```

Deployment files present:

```text
compose.oracle.yml
.env.oracle.example
```

Observed modes/sizes:

```text
.env.oracle.example  1288 bytes
compose.oracle.yml   5482 bytes
```

---

# 11. Oracle environment configuration

Real Oracle env file:

```text
~/finance_project/.env.oracle
```

Permissions:

```text
-rw-------
```

Mode:

```text
600
```

It was copied from:

```text
.env.oracle.example
```

The real `.env.oracle` values are configured. **Do not replace them and do not print them.**

Validated state:

```text
POSTGRES_PASSWORD: SET
DATABASE_URL: SET
JWT_SECRET_KEY: SET
ENCRYPTION_KEY: SET
MINIO_ROOT_USER: SET
MINIO_ROOT_PASSWORD: SET
ARTIFACT_S3_ACCESS_KEY: SET
ARTIFACT_S3_SECRET_KEY: SET
ENCRYPTION_KEY valid Fernet size: True
MinIO access keys match: True
MinIO secret keys match: True
```

### Important encryption-key fact

The production/canonical `ENCRYPTION_KEY` was **not regenerated**.

It was taken from the Mac file:

```text
apps/api/.env
```

and transferred into Oracle without displaying its value.

This is essential because existing encrypted LLM/API credentials in the database may depend on that same Fernet key.

Do not regenerate the production `ENCRYPTION_KEY`.

### Non-secret `.env.oracle` configuration baseline

The example contains:

```dotenv
APP_ENV=production
POSTGRES_DB=psx_ai
POSTGRES_USER=psx
DATABASE_POOL_SIZE=12
DATABASE_MAX_OVERFLOW=4
ENABLE_DEMO_ACCESS=false
ALLOW_MOCK_IN_PRODUCTION=false
AUTO_CREATE_TABLES=false
CORS_ORIGINS=http://localhost:3000
MARKET_DATA_MODE=auto
MARKET_HISTORY_BOOTSTRAP_ENABLED=false
SCHEDULED_RESEARCH_ENABLED=false
MACRO_INGESTION_ENABLED=false
EVIDENCE_ENABLED=false
CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/1
ARTIFACT_STORAGE_BACKEND=s3
ARTIFACT_S3_ENDPOINT_URL=http://minio:9000
ARTIFACT_S3_REGION=us-east-1
ARTIFACT_S3_BUCKET=psx-artifacts
ARTIFACT_S3_ADDRESSING_STYLE=path
EVIDENCE_SPOOL_ROOT=/data/evidence-spool
API_INTERNAL_BASE_URL=http://api:8000
NEXT_PUBLIC_API_BASE_URL=/api
EMBEDDING_BACKEND=sentence_transformers
EMBEDDING_MODEL_NAME=sentence-transformers/all-MiniLM-L6-v2
```

Secret values are intentionally omitted.

---

# 12. Docker image build

Command run on Oracle:

```bash
cd ~/finance_project
docker compose -f compose.oracle.yml build api web
```

Build completed successfully:

```text
[+] build 2/2
✔ Image psx-ai-portfolio-web:oracle Built
✔ Image psx-ai-portfolio-api:oracle Built
```

Total build time:

```text
~752.5 seconds
```

Notable slow steps:

```text
API pip install: ~323.6 s
API image export: ~345.7 s
Web npm build: ~75.6 s
```

The build proved the app can build on ARM64/Ampere.

---

# 13. Oracle storage services currently running

Command used:

```bash
docker compose -f compose.oracle.yml up -d postgres redis minio minio-init
```

Pulled/started:

```text
redis:7-alpine
quay.io/minio/minio:RELEASE.2025-09-07T16-13-09Z
quay.io/minio/mc:RELEASE.2025-08-13T08-35-41Z
pgvector/pgvector:pg16
```

Containers observed:

```text
finance_project-minio-1
finance_project-postgres-1
finance_project-redis-1
```

Ports observed:

```text
MinIO:      127.0.0.1:9000-9001 -> container 9000-9001
PostgreSQL: 127.0.0.1:5432      -> container 5432
Redis:      127.0.0.1:6379      -> container 6379
```

The services are usable; PostgreSQL was successfully used later to validate the dump.

`minio-init` was started as a one-time initializer. Its final exit status was not pasted into this chat, so if needed later verify with:

```bash
docker compose -f compose.oracle.yml ps -a minio-init
```

---

# 14. Local Mac ingestion freeze

The migration requires local ingestion/schedulers to stay stopped so the canonical source does not continue changing mid-transfer.

Original command run:

```bash
docker compose --profile ingestion --profile scheduling stop
docker compose --profile ingestion --profile scheduling rm -f
```

This unexpectedly also stopped/removed local `postgres` and `redis` containers because of Compose dependency/profile behavior.

The data volumes were **not deleted**.

Local PostgreSQL and Redis were then recreated safely with:

```bash
docker compose up -d postgres redis
```

Current intended local state:

- PostgreSQL: running
- Redis: running
- ingestion workers: stopped/removed
- phase2 scheduler: stopped/removed
- evidence scheduler: stopped/removed
- no worker containers running

`docker ps --format '{{.Names}}'` showed only:

```text
finance_project-postgres-1
finance_project-redis-1
```

Local port mapping observed:

```text
PostgreSQL host port 5433 -> container port 5432
Redis host port 6379      -> container port 6379
```

Do not restart ingestion/scheduling until the migration is complete.

---

# 15. Local PostgreSQL source database facts

Database:

```text
psx_ai
```

User:

```text
psx
```

Measured database size:

```text
902 MB
```

Number of user tables:

```text
74
```

Top table sizes measured locally:

| Table | Total | Table only | Indexes |
|---|---:|---:|---:|
| `document_chunks` | 478 MB | 80 MB | 115 MB |
| `market_observations` | 99 MB | 51 MB | 47 MB |
| `sector_daily_stats` | 57 MB | 10 MB | 46 MB |
| `market_prices` | 43 MB | 26 MB | 17 MB |
| `ingestion_coverage` | 36 MB | 25 MB | 11 MB |
| `macro_observations` | 27 MB | 18 MB | 9664 kB |
| `discovery_candidates` | 23 MB | 14 MB | 9184 kB |
| `source_artifacts` | 22 MB | 15 MB | 7936 kB |
| `citations` | 20 MB | 15 MB | 5224 kB |
| `documents` | 11 MB | 6896 kB | 4424 kB |
| `document_pages` | 11 MB | 2832 kB | 1032 kB |
| `financial_facts` | 10 MB | 9240 kB | 1056 kB |
| `standardized_financial_facts` | 9072 kB | 4552 kB | 4480 kB |
| `events` | 7360 kB | 4912 kB | 2408 kB |
| `event_sources` | 5784 kB | 2488 kB | 3256 kB |
| `normalized_events` | 5672 kB | 3080 kB | 2552 kB |
| `normalized_event_subjects` | 5584 kB | 2048 kB | 3504 kB |
| `assistant_executions` | 4408 kB | 112 kB | 64 kB |
| `normalized_event_evidence` | 3352 kB | 1248 kB | 2072 kB |
| `assistant_attempts` | 2816 kB | 80 kB | 32 kB |

This explains why the database itself is under 1 GB while the project’s artifacts are ~12 GB.

---

# 16. PostgreSQL dump migration — COMPLETE

Source command from Mac:

```bash
docker compose exec -T postgres \
  pg_dump -U psx -d psx_ai -Fc \
  | ssh -i ~/.ssh/oracle_psx ubuntu@141.145.146.120 \
    'cat > /srv/psx/import/psx_ai.dump'
```

Oracle dump path:

```text
/srv/psx/import/psx_ai.dump
```

Final observed size:

```text
210 MB
```

This size is plausible because:

- source DB is 902 MB,
- `pg_dump -Fc` is compressed,
- indexes are recreated rather than copied as raw on-disk index files,
- the 12 GB artifact directory is separate from PostgreSQL.

### Dump header verification

Command:

```bash
head -c 16 /srv/psx/import/psx_ai.dump | xxd
```

Output began:

```text
5047 444d 50...
PGDMP...
```

So it is a PostgreSQL custom-format archive.

### Important `pg_restore` invocation correction

This form **did not work** inside the Docker container:

```bash
pg_restore -l /dev/stdin
```

It produced:

```text
pg_restore: error: did not find magic string in file header
```

The working validation method is to pipe the dump to `pg_restore` **without a filename**:

```bash
cat /srv/psx/import/psx_ai.dump \
  | docker compose -f compose.oracle.yml exec -T postgres \
      pg_restore -l \
  >/dev/null \
  && echo "DUMP ARCHIVE IS VALID"
```

Result:

```text
DUMP ARCHIVE IS VALID
```

Table-data count:

```bash
cat /srv/psx/import/psx_ai.dump \
  | docker compose -f compose.oracle.yml exec -T postgres \
      pg_restore -l \
  | grep 'TABLE DATA' \
  | wc -l
```

Result:

```text
74
```

That matches the source database’s 74 user tables and is a strong validation.

**Do not redo the DB dump.**

---

# 17. Artifact migration facts

Local normal artifact directory:

```text
apps/api/data/artifacts/
```

Measured size:

```text
12G
```

The rsync scan shows roughly:

```text
22001 items
```

Files include:

```text
.evidence-spool/
2026/
2026/08/...
.bin
.json
.html
...
```

Old Docker artifact volume name:

```text
finance_project_source_artifacts
```

That volume has **not yet been transferred**.

---

# 18. CURRENT ACTIVE COMMAND — Phase 20 host-artifact transfer

The Mac’s built-in `rsync` does **not** support:

```text
--info=progress2
```

Attempting it produced:

```text
rsync: unrecognized option `--info=progress2'
```

The active/supported macOS transfer command is:

```bash
cd /Users/Raahim/Documents/LUMS/Junior/summer_semester/Tintash/finance_project

rsync -aP \
  -e "ssh -i $HOME/.ssh/oracle_psx" \
  apps/api/data/artifacts/ \
  ubuntu@141.145.146.120:/srv/psx/import/host-artifacts/
```

`-P` is equivalent to:

```text
--partial
--progress
```

So it preserves partial files and shows per-file progress.

At the time this handoff file was requested, this command was actively transferring files.

Last visible progress in chat was approximately:

```text
xfer#64
to-check=69/22001
```

and it had reached files under:

```text
2026/08/11/
```

Typical displayed transfer speeds were around:

```text
~2–5 MB/s
```

with some small files transferring much faster.

## Important behavior if interrupted

If the transfer stops because of SSH/network loss, safely rerun the **same** command:

```bash
rsync -aP \
  -e "ssh -i $HOME/.ssh/oracle_psx" \
  apps/api/data/artifacts/ \
  ubuntu@141.145.146.120:/srv/psx/import/host-artifacts/
```

Rsync will avoid retransferring files already completed and will retain partial files.

## Optional overall progress instead of per-file progress

macOS’s stock `rsync` is old.

If desired, Homebrew modern rsync can be installed:

```bash
brew install rsync
```

Apple Silicon path:

```text
/opt/homebrew/bin/rsync
```

Then use:

```bash
/opt/homebrew/bin/rsync -a --partial \
  --info=progress2 \
  -e "ssh -i $HOME/.ssh/oracle_psx" \
  apps/api/data/artifacts/ \
  ubuntu@141.145.146.120:/srv/psx/import/host-artifacts/
```

This gives one overall transfer progress indicator.

However, if the current `rsync -aP` is still running normally, there is no need to interrupt it.

---

# 19. Exact next step after current rsync finishes

On Oracle:

```bash
du -sh /srv/psx/import/host-artifacts
```

Expected ballpark:

```text
~12G
```

Also check:

```bash
df -h /srv/psx
```

Do not start Phase 21 until the current host-artifact transfer has completed or been intentionally resumed to completion.

---

# 20. Phase 21 — transfer old Docker artifact volume

Exact source volume:

```text
finance_project_source_artifacts
```

First inspect it on the Mac:

```bash
docker volume inspect finance_project_source_artifacts
```

Measure it:

```bash
docker run --rm \
  -v finance_project_source_artifacts:/from:ro \
  alpine \
  sh -c 'du -sh /from'
```

Then transfer it:

```bash
docker run --rm \
  -v finance_project_source_artifacts:/from:ro \
  alpine \
  tar -C /from -cf - . \
  | ssh -i ~/.ssh/oracle_psx ubuntu@141.145.146.120 \
    'mkdir -p /srv/psx/import/volume-artifacts &&
     tar -C /srv/psx/import/volume-artifacts -xf -'
```

Nothing is deleted locally.

Afterward, on Oracle:

```bash
du -sh \
  /srv/psx/import/host-artifacts \
  /srv/psx/import/volume-artifacts

df -h /srv/psx
```

---

# 21. Phase 22 — restore PostgreSQL on Oracle

Original runbook used `/dev/stdin`, but validation showed the safer working form is to pipe the archive to `pg_restore` without naming `/dev/stdin`.

Preferred restore:

```bash
cd ~/finance_project

cat /srv/psx/import/psx_ai.dump \
  | docker compose -f compose.oracle.yml exec -T postgres \
      pg_restore \
      -U psx \
      -d psx_ai \
      --clean \
      --if-exists \
      --no-owner
```

Warnings about initially missing objects during `--clean --if-exists` may occur. Actual restore errors must be investigated before continuing.

Then:

```bash
docker compose -f compose.oracle.yml run --rm api \
  alembic upgrade head
```

Do not continue if the restore genuinely fails.

---

# 22. Phase 23 — artifact migration inventory

Run from Oracle:

```bash
cd ~/finance_project

docker compose -f compose.oracle.yml run --rm api \
  python -m app.jobs.migrate_artifacts \
  --path-map '/Users/Raahim/Documents/LUMS/Junior/summer_semester/Tintash/finance_project/apps/api/data/artifacts=/import/host-artifacts' \
  --path-map '/data/artifacts=/import/volume-artifacts' \
  --scan-root /import/host-artifacts \
  --scan-root /import/volume-artifacts
```

This is read-only inventory mode.

Do not apply if there are unexplained:

```text
missing
hash_mismatch
unreferenced_missing
```

---

# 23. Phase 24 — apply artifact migration into MinIO

Only after inventory is clean:

```bash
docker compose -f compose.oracle.yml run --rm api \
  python -m app.jobs.migrate_artifacts --apply \
  --path-map '/Users/Raahim/Documents/LUMS/Junior/summer_semester/Tintash/finance_project/apps/api/data/artifacts=/import/host-artifacts' \
  --path-map '/data/artifacts=/import/volume-artifacts' \
  --scan-root /import/host-artifacts \
  --scan-root /import/volume-artifacts \
  --manifest /backups/artifact-migration-manifest.json
```

---

# 24. Phase 25 — verify artifact migration

```bash
docker compose -f compose.oracle.yml run --rm api \
  python -m app.jobs.migrate_artifacts --verify \
  --scan-root /import/host-artifacts \
  --scan-root /import/volume-artifacts
```

Hard stop if any entries exist in:

```text
missing
hash_mismatch
unreferenced_missing
```

---

# 25. Phase 26 — create remote development DB

While ingestion remains stopped:

```bash
docker compose -f compose.oracle.yml exec -T postgres sh -c \
  'pg_dump -U "$POSTGRES_USER" -Fc psx_ai > /tmp/psx_ai_dev.dump &&
   dropdb -U "$POSTGRES_USER" --if-exists psx_ai_dev &&
   createdb -U "$POSTGRES_USER" -O "$POSTGRES_USER" psx_ai_dev &&
   pg_restore -U "$POSTGRES_USER" -d psx_ai_dev --no-owner /tmp/psx_ai_dev.dump &&
   rm /tmp/psx_ai_dev.dump'
```

Then remove cloned LLM keys from development:

```bash
docker compose -f compose.oracle.yml exec -T postgres \
  psql -U psx -d psx_ai_dev \
  -c 'TRUNCATE TABLE llm_api_keys;'
```

Resulting intended DBs:

```text
psx_ai       = canonical / hosted application
psx_ai_dev   = fixed remote development snapshot
```

There is **no automatic canonical→dev synchronization yet**.

---

# 26. Phase 27 — start hosted app

```bash
docker compose -f compose.oracle.yml up -d --build
docker compose -f compose.oracle.yml ps
```

Confirm no worker/scheduler appears unexpectedly.

From Oracle:

```bash
curl --fail http://127.0.0.1:3000/api/health
curl --fail http://127.0.0.1:3000/api/ready
```

`/ready` should show PostgreSQL, Redis, and artifact storage healthy.

---

# 27. Phase 28 — SSH tunnel from Mac

Use:

```bash
ssh -i ~/.ssh/oracle_psx -N \
  -L 13000:127.0.0.1:3000 \
  -L 15432:127.0.0.1:5432 \
  -L 16379:127.0.0.1:6379 \
  -L 19000:127.0.0.1:9000 \
  ubuntu@141.145.146.120
```

Mappings:

```text
Mac localhost:13000 -> Oracle 127.0.0.1:3000
Mac localhost:15432 -> Oracle 127.0.0.1:5432
Mac localhost:16379 -> Oracle 127.0.0.1:6379
Mac localhost:19000 -> Oracle 127.0.0.1:9000
```

Hosted app:

```text
http://localhost:13000
```

---

# 28. Phase 29 — local development env against Oracle

On Mac:

```bash
cd /Users/Raahim/Documents/LUMS/Junior/summer_semester/Tintash/finance_project

cp .env.remote.example apps/api/.env.remote
chmod 600 apps/api/.env.remote
```

Use the variable names provided by `.env.remote.example`.

Conceptual connection targets:

```text
PostgreSQL host: 127.0.0.1
PostgreSQL port: 15432
Database:        psx_ai_dev

Redis host:      127.0.0.1
Redis port:      16379

MinIO host:      127.0.0.1
MinIO port:      19000
```

Because `psx_ai_dev.llm_api_keys` is cleared, use a **new development-only Fernet key** for `.env.remote`.

Do not reuse the production encryption-key requirement here unless the app specifically needs it for some remaining dev data.

---

# 29. Phase 30 — local API

On Mac:

```bash
cd /Users/Raahim/Documents/LUMS/Junior/summer_semester/Tintash/finance_project/apps/api

set -a
source .env.remote
set +a

uvicorn app.main:app --reload \
  --host 127.0.0.1 \
  --port 8000
```

---

# 30. Phase 31 — local web

In another Mac terminal:

```bash
cd /Users/Raahim/Documents/LUMS/Junior/summer_semester/Tintash/finance_project/apps/web

API_INTERNAL_BASE_URL=http://127.0.0.1:8000 npm run dev
```

Open:

```text
http://localhost:3000
```

---

# 31. Phase 32 — two operating modes

## Hosted mode

```text
Mac browser
    ↓ SSH tunnel
Oracle web
    ↓
Oracle API
    ↓
Oracle PostgreSQL / Redis / MinIO
```

URL:

```text
http://localhost:13000
```

## Local-development mode

```text
Mac web :3000
    ↓
Mac API :8000
    ↓ SSH tunnel
Oracle PostgreSQL / Redis / MinIO
```

URL:

```text
http://localhost:3000
```

---

# 32. Phase 33 — manual ingestion controls

One-time market refresh:

```bash
./ops/ingestion run market
```

Phase 2:

```bash
./ops/ingestion start phase2

docker compose -f compose.oracle.yml \
  --profile scheduling up -d phase2-scheduler
```

Stop producer first:

```bash
docker compose -f compose.oracle.yml \
  --profile scheduling stop phase2-scheduler
```

After queued work drains:

```bash
./ops/ingestion stop phase2
```

Other controls:

```bash
./ops/ingestion start macro
./ops/ingestion start evidence
./ops/ingestion status
./ops/ingestion stop all
```

Normal reboot behavior intended:

- PostgreSQL starts
- Redis starts
- MinIO starts
- API starts
- web starts
- ingestion workers/schedulers do **not** automatically start

---

# 33. Phase 34 — canonical database backup

After hosted app and migration are verified:

```bash
docker compose -f compose.oracle.yml exec -T postgres \
  pg_dump -U psx -d psx_ai -Fc \
  > /srv/psx/backups/psx_ai-initial-verified.dump
```

Verify it exists and has nonzero size:

```bash
ls -lh /srv/psx/backups/
```

---

# 34. Phase 35 — OCI block-volume backup

In Oracle Cloud Console:

```text
Storage
→ Block Storage
→ Block Volumes
→ psx-data
→ Create Backup
```

No automatic backup policy was selected earlier.

The migration plan intentionally creates the block-volume backup **after** the restored database/artifacts have been verified.

Keep the import copy until both:

1. the database dump backup is verified, and
2. the OCI block-volume backup is verified.

---

# 35. Phase 36 — prove local Mac storage is unnecessary

On Mac:

```bash
cd /Users/Raahim/Documents/LUMS/Junior/summer_semester/Tintash/finance_project

docker compose stop postgres redis
```

With the SSH tunnel active, restart local API/web against Oracle remote services.

Test all of:

- login
- portfolios
- market pages
- charts
- document retrieval
- one PDF/document parse
- `/health`
- `/ready`
- Oracle-hosted app at `localhost:13000`
- local-development app at `localhost:3000`

Only if all of these work should local storage removal even be considered.

---

# 36. Phase 37 — optional local cleanup

Only after all verification + backups:

Potentially remove:

```text
apps/api/data/artifacts
finance_project_source_artifacts Docker volume
local PostgreSQL Docker volume
```

Do **not** use:

```bash
docker volume prune
```

because it can remove unrelated project data.

Remove exact known resources only.

---

# 37. Known mistakes / corrections already discovered

These are important so a new chat does not repeat them.

## A. Inline VCN creation did not allow public IPv4

Problem:

The VM wizard’s inline “Create new VCN / public subnet” flow left the public IPv4 control disabled.

Resolution:

Created networking manually:

```text
psx-vcn
10.0.0.0/16

psx-internet-gateway

Default route:
0.0.0.0/0 -> psx-internet-gateway

psx-public-subnet
10.0.0.0/24
```

Then selected the existing VCN/subnet in the VM wizard, after which public IPv4 became available.

Do not redo networking.

---

## B. “Attach block volume” button was initially greyed out

Resolution:

Created the block volume separately under OCI Block Storage first:

```text
psx-data
150 GB
```

Then attached it to `psx-oracle`.

Do not create another data disk.

---

## C. `docker compose ... stop/rm` also removed local PostgreSQL/Redis containers

This did not delete volumes.

They were safely recreated with:

```bash
docker compose up -d postgres redis
```

Ingestion/scheduler containers remain stopped/removed.

Do not run `down -v`.

---

## D. `pg_restore -l /dev/stdin` failed

The dump itself was valid.

Header showed:

```text
PGDMP
```

Working validation form:

```bash
cat /srv/psx/import/psx_ai.dump \
  | docker compose -f compose.oracle.yml exec -T postgres \
      pg_restore -l
```

Use stdin without specifying `/dev/stdin`.

---

## E. macOS stock `rsync` does not support `--info=progress2`

Failed:

```text
rsync: unrecognized option `--info=progress2'
```

Working stock-macOS command:

```bash
rsync -aP \
  -e "ssh -i $HOME/.ssh/oracle_psx" \
  apps/api/data/artifacts/ \
  ubuntu@141.145.146.120:/srv/psx/import/host-artifacts/
```

Optional Homebrew modern rsync can use `--info=progress2`.

---

# 38. Current-state quick reference

## Mac

Project:

```text
/Users/Raahim/Documents/LUMS/Junior/summer_semester/Tintash/finance_project
```

SSH key:

```text
~/.ssh/oracle_psx
```

Local DB:

```text
psx_ai
902 MB
74 user tables
```

Local running Docker services:

```text
finance_project-postgres-1
finance_project-redis-1
```

Local Postgres host port:

```text
5433
```

Local Redis host port:

```text
6379
```

Local artifact dir:

```text
apps/api/data/artifacts/
~12 GB
```

Old artifact volume:

```text
finance_project_source_artifacts
```

Ingestion/schedulers:

```text
STOPPED / REMOVED
```

---

## Oracle

Public IPv4:

```text
141.145.146.120
```

SSH:

```bash
ssh -i ~/.ssh/oracle_psx ubuntu@141.145.146.120
```

Project:

```text
~/finance_project
```

Branch:

```text
main
```

VM:

```text
psx-oracle
Ubuntu 24.04
A1 Flex
2 OCPU
12 GB RAM
```

Data disk:

```text
/dev/sdb
150 GB
ext4
mounted at /srv/psx
```

Oracle DB dump:

```text
/srv/psx/import/psx_ai.dump
~210 MB
VALID PostgreSQL custom archive
74 TABLE DATA entries
```

Host-artifact destination:

```text
/srv/psx/import/host-artifacts/
```

Docker-volume artifact destination:

```text
/srv/psx/import/volume-artifacts/
```

Storage service containers:

```text
finance_project-postgres-1
finance_project-redis-1
finance_project-minio-1
```

Docker images built:

```text
psx-ai-portfolio-api:oracle
psx-ai-portfolio-web:oracle
```

---

# 39. Single most important current instruction

**At handoff, the 12 GB host artifact rsync is in progress.**

Do not skip ahead until it either:

1. finishes and returns the Mac shell prompt, or
2. is interrupted and safely resumed to completion.

After completion, verify on Oracle:

```bash
du -sh /srv/psx/import/host-artifacts
df -h /srv/psx
```

Then continue with Phase 21 (`finance_project_source_artifacts` Docker-volume transfer).

---

# 40. Primary runbook

The repository’s deployment runbook is:

```text
docs/oracle-deployment.md
```

Original local repo path:

```text
/Users/Raahim/Documents/LUMS/Junior/summer_semester/Tintash/finance_project
```

The migration strategy is intentionally conservative:

- preserve all Mac data,
- move DB + both artifact sources,
- restore and verify,
- create dev snapshot,
- run hosted + remote-development modes,
- back up Oracle,
- prove local data is no longer needed,
- only then delete local copies.

