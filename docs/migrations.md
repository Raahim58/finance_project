# Migration and Recovery Notes

Workstation checkpoints include `0006_domain_data` through `0012_audit_events`. Phase-1 ingestion observability is migration `0013_ingestion_observability`; it adds update counts, structured diagnostics, and resulting-observation timestamps to canonical ingestion runs.

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
