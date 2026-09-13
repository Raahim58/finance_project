# Migration and Recovery Notes

Phase 7A durable context deficiencies, refresh aggregation, and compact build
receipts are added by `0025_phase7a_canonical_context`. It also adds the durable
ingestion-work links and compact refresh-notification outbox used for automatic
terminal rebuilds. The migration stores no assembled context payloads and seeds no
financial data.

Phase 7B consumer audit linkage is added by `0026_phase7b_context_consumers`.
Receipt and refresh rows gain consumer/output references; Assistant messages gain
an optional context-receipt reference, linked parent message, and message kind for
deterministic refresh follow-ups. Existing Assistant messages are retained and
receive the `answer` compatibility default. The migration stores no permanent full
context object and seeds no financial data.

Bounded per-call LLM diagnostics are added by
`0027_llm_invocation_diagnostics`. The table links each provider attempt to its user,
conversation, and Assistant message and stores safe operational/error metadata. It
does not store API keys, authorization headers, or full outgoing prompts.

Durable native tool-loop continuation is added by `0029_assistant_tool_loop`. It adds
the nullable encrypted `assistant_executions.transcript_encrypted` checkpoint. Existing
executions remain readable and require no fabricated backfill. Downgrade removes only
that checkpoint column; take a backup first because in-progress transcripts cannot be
recovered after downgrade.

Workstation checkpoints include `0006_domain_data` through `0012_audit_events`. Ingestion observability is migration `0013_ingestion_observability`. Phase 2 worker coverage, secondary standardized facts, persisted screening snapshots, and official-fact extraction provenance are migration `0014_phase2_ingestion_plane`. Global Evidence v1 source configuration/state, discovery candidates, and event-cluster/source-selection fields are migration `0015_global_evidence_v1`. Pass 2 targeted and historical refresh requests use the durable ledger added by `0016_evidence_refresh_requests`. Pass 3 resumable cursors, date bounds, budgets, counters, and continuous source-health timestamps are migration `0017_evidence_history`.

```bash
cd apps/api
source .venv/bin/activate
alembic current
alembic upgrade head
```

Pass 0 migration verification, including its reversible boundary:

```bash
DATABASE_URL=sqlite:////tmp/psx-evidence-migration.sqlite alembic upgrade head
DATABASE_URL=sqlite:////tmp/psx-evidence-migration.sqlite alembic downgrade 0014_phase2_ingestion_plane
DATABASE_URL=sqlite:////tmp/psx-evidence-migration.sqlite alembic upgrade head
```

Migration `0015` does not seed or enable any source. Existing events receive only compatibility defaults (`cluster_status=active`, `cluster_version=deterministic-v1`, and `selection_status=legacy` for their sources); it does not fabricate topics, entities, scores, or evidence.

Before production migration, back up PostgreSQL and rehearse against a restored copy. Migration `0006` preserves legacy companies, holdings, and transactions, backfills a generic equity instrument for each company, links holdings/transactions, and writes a dated position baseline. It deliberately marks pre-baseline history incomplete rather than inventing cash or performance.

SQLite migration smoke test:

```bash
DATABASE_URL=sqlite:////tmp/psx-migration.sqlite alembic upgrade head
DATABASE_URL=sqlite:////tmp/psx-migration.sqlite alembic downgrade base
DATABASE_URL=sqlite:////tmp/psx-migration.sqlite alembic upgrade head
```

The automated `test_migrations.py` additionally upgrades a populated `0005` database and verifies instrument/reference backfill and honest baseline history. Downgrades remove workstation tables/columns, so only use them on disposable databases or after a verified backup.
