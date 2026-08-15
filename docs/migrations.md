# Migration and Recovery Notes

Workstation checkpoints include `0006_domain_data` through `0012_audit_events`. Ingestion observability is migration `0013_ingestion_observability`. Phase 2 worker coverage, secondary standardized facts, persisted screening snapshots, and official-fact extraction provenance are migration `0014_phase2_ingestion_plane`.

```bash
cd apps/api
source .venv/bin/activate
alembic current
alembic upgrade head
```

Before production migration, back up PostgreSQL and rehearse against a restored copy. Migration `0006` preserves legacy companies, holdings, and transactions, backfills a generic equity instrument for each company, links holdings/transactions, and writes a dated position baseline. It deliberately marks pre-baseline history incomplete rather than inventing cash or performance.

SQLite migration smoke test:

```bash
DATABASE_URL=sqlite:////tmp/psx-migration.sqlite alembic upgrade head
DATABASE_URL=sqlite:////tmp/psx-migration.sqlite alembic downgrade base
DATABASE_URL=sqlite:////tmp/psx-migration.sqlite alembic upgrade head
```

The automated `test_migrations.py` additionally upgrades a populated `0005` database and verifies instrument/reference backfill and honest baseline history. Downgrades remove workstation tables/columns, so only use them on disposable databases or after a verified backup.
