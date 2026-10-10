# Schema baseline

The active migration is a frozen snapshot of the original 39-revision chain,
retaining its last identifier, `0039_ai_briefs`. Databases already at that head
need no stamping or data rewrites. Fresh installs create the final schema directly.
Future schema changes use new incremental revisions; the baseline never imports
application model metadata.

## Current or empty databases

Run with the intended database's normal server configuration:

```bash
cd apps/api
alembic current
alembic upgrade head
```

## Databases at an older revision

Back up first and rehearse on a restored copy. Complete the original chain from
its pinned source before using the current checkout:

```bash
git worktree add --detach /tmp/psx-pre-baseline e7046f77278619de1d83bf23b709d66eb74d255a
cd /tmp/psx-pre-baseline/apps/api
# Use the installed backend environment and the intended DATABASE_URL.
# This detached worktree does not contain your .env file.
python -m alembic upgrade 0039_ai_briefs
python -m alembic current
```

Then return to the current checkout and run `alembic upgrade head`. The deployment
preflight rejects unsupported old revisions. Never stamp an unfinished old schema:
that would skip required portfolio, evidence and other data transformations.

## Verification and rollback

```bash
cd apps/api
.venv/bin/python -m pytest app/tests/test_migrations.py app/tests/test_oracle_deploy.py -q
```

The tests reconstruct the legacy chain from the pinned Git commit and compare
its schema with the baseline, exercise populated upgrades, and check that rejected
old databases and current-head databases retain their records. Keep that commit
available in checkouts used for migration testing or legacy restores.

Older intermediate downgrade targets require the original checkout. Downgrading
the baseline to `base` drops the entire application schema and requires an explicit
option. Use it only on disposable databases or as part of a verified restore:

```bash
alembic -x allow_baseline_drop=true downgrade base
alembic upgrade head
```

The baseline includes PostgreSQL vector/HNSW indexes, lexical GIN indexes and
search triggers, partial indexes, constraints and server defaults. SQLite uses
its supported text-vector representation. This migration seeds no market or user
data; demo seeding is separate.
