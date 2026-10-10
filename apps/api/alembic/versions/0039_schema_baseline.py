"""Frozen schema baseline through 0039_ai_briefs.

The deployed head identifier is retained so fully upgraded databases are a no-op.
Older databases must finish the original chain before using this baseline.
This snapshot intentionally does not import application model metadata.
"""
from alembic import context, op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from pgvector.sqlalchemy import Vector

revision = "0039_ai_briefs"
down_revision = None
branch_labels = depends_on = None


def upgrade():
    if op.get_bind().dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table('assistant_provider_queue',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('credential_hash', sa.String(length=64), nullable=False),
    sa.Column('priority', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_assistant_provider_queue_credential_hash', 'assistant_provider_queue', ['credential_hash'], unique=False)
    op.create_index('ix_assistant_provider_queue_expires_at', 'assistant_provider_queue', ['expires_at'], unique=False)
    op.create_table('company_marks',
    sa.Column('symbol', sa.String(length=30), nullable=False),
    sa.Column('website', sa.String(length=500), nullable=True),
    sa.Column('profile_source_url', sa.String(length=500), nullable=False),
    sa.Column('image_source_url', sa.String(length=1000), nullable=True),
    sa.Column('content', sa.LargeBinary(), nullable=True),
    sa.Column('sha256', sa.String(length=64), nullable=True),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.Column('checked_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('symbol')
    )
    op.create_table('context_deficiencies',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('fingerprint', sa.String(length=64), nullable=False),
    sa.Column('entity_type', sa.String(length=40), nullable=False),
    sa.Column('entity_key', sa.String(length=160), nullable=False),
    sa.Column('category', sa.String(length=80), nullable=False),
    sa.Column('payload_json', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('occurrence_count', sa.Integer(), nullable=False),
    sa.Column('first_seen_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('fingerprint', name='uq_context_deficiency_fingerprint')
    )
    op.create_index('ix_context_deficiencies_category', 'context_deficiencies', ['category'], unique=False)
    op.create_index('ix_context_deficiencies_entity_key', 'context_deficiencies', ['entity_key'], unique=False)
    op.create_index('ix_context_deficiencies_fingerprint', 'context_deficiencies', ['fingerprint'], unique=False)
    op.create_index('ix_context_deficiencies_status', 'context_deficiencies', ['status'], unique=False)
    op.create_table('data_sources',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('source_type', sa.String(length=40), nullable=False),
    sa.Column('base_url', sa.String(length=500), nullable=True),
    sa.Column('priority', sa.Integer(), nullable=False),
    sa.Column('freshness_sla_minutes', sa.Integer(), nullable=True),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('use_notes', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name')
    )
    op.create_table('events',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('event_type', sa.String(length=60), nullable=False),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('materiality', sa.String(length=20), nullable=True),
    sa.Column('direction', sa.String(length=20), nullable=True),
    sa.Column('confidence', sa.Numeric(precision=8, scale=6), nullable=True),
    sa.Column('details_json', sa.Text(), nullable=False),
    sa.Column('event_time_end', sa.DateTime(timezone=True), nullable=True),
    sa.Column('cluster_key', sa.String(length=64), nullable=True),
    sa.Column('topic', sa.String(length=120), nullable=True),
    sa.Column('geography', sa.String(length=80), nullable=True),
    sa.Column('cluster_status', sa.String(length=30), server_default=sa.text("'active'"), nullable=False),
    sa.Column('cluster_version', sa.String(length=40), server_default=sa.text("'deterministic-v1'"), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('cluster_key', name='uq_event_cluster_key')
    )
    op.create_index('ix_event_geography_occurred', 'events', ['geography', 'occurred_at'], unique=False)
    op.create_index('ix_event_topic_occurred', 'events', ['topic', 'occurred_at'], unique=False)
    op.create_table('exchanges',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('code', sa.String(length=20), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('timezone', sa.String(length=80), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_exchanges_code', 'exchanges', ['code'], unique=1)
    op.create_table('ingestion_runs',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('job_key', sa.String(length=120), nullable=False),
    sa.Column('run_key', sa.String(length=160), nullable=False),
    sa.Column('provider', sa.String(length=80), nullable=False),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('parent_run_id', sa.String(length=36), nullable=True),
    sa.Column('attempted_count', sa.Integer(), nullable=False),
    sa.Column('accepted_count', sa.Integer(), nullable=False),
    sa.Column('rejected_count', sa.Integer(), nullable=False),
    sa.Column('retry_count', sa.Integer(), nullable=False),
    sa.Column('error_class', sa.String(length=160), nullable=True),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('updated_count', sa.Integer(), server_default=sa.text("'0'"), nullable=False),
    sa.Column('diagnostics_json', sa.Text(), server_default=sa.text("'{}'"), nullable=False),
    sa.Column('latest_observation_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['parent_run_id'], ['ingestion_runs.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('job_key', 'run_key', name='uq_ingestion_job_run')
    )
    op.create_table('ingestion_stage_runs',
    sa.Column('stage', sa.String(length=40), nullable=False),
    sa.Column('subject_key', sa.String(length=160), nullable=False),
    sa.Column('input_hash', sa.String(length=64), nullable=False),
    sa.Column('code_version', sa.String(length=40), nullable=False),
    sa.Column('mode', sa.String(length=20), nullable=False),
    sa.Column('input', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('output', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.Column('attempt_count', sa.Integer(), nullable=False),
    sa.Column('lease_token', sa.String(length=36), nullable=True),
    sa.Column('lease_until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('heartbeat_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('next_attempt_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('dispatch_until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('error_code', sa.String(length=100), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('stage', 'subject_key', 'input_hash', 'code_version', name='uq_pipeline_stage_input')
    )
    op.create_index('ix_pipeline_dispatch', 'ingestion_stage_runs', ['status', 'next_attempt_at', 'mode'], unique=False)
    op.create_index('ix_pipeline_lease', 'ingestion_stage_runs', ['status', 'lease_until'], unique=False)
    op.create_table('market_ingestion_runs',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('mode', sa.String(length=20), nullable=False),
    sa.Column('attempted_provider', sa.String(length=80), nullable=False),
    sa.Column('used_provider', sa.String(length=80), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('latest_trade_date', sa.Date(), nullable=True),
    sa.Column('records_written', sa.Integer(), nullable=False),
    sa.Column('message', sa.Text(), nullable=True),
    sa.Column('attempted_count', sa.Integer(), server_default=sa.text("'0'"), nullable=False),
    sa.Column('accepted_count', sa.Integer(), server_default=sa.text("'0'"), nullable=False),
    sa.Column('rejected_count', sa.Integer(), server_default=sa.text("'0'"), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_market_ingestion_runs_attempted_provider', 'market_ingestion_runs', ['attempted_provider'], unique=False)
    op.create_index('ix_market_ingestion_runs_mode', 'market_ingestion_runs', ['mode'], unique=False)
    op.create_index('ix_market_ingestion_runs_status', 'market_ingestion_runs', ['status'], unique=False)
    op.create_index('ix_market_ingestion_runs_used_provider', 'market_ingestion_runs', ['used_provider'], unique=False)
    op.create_table('market_snapshots',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('snapshot_date', sa.Date(), nullable=False),
    sa.Column('index_name', sa.String(length=120), nullable=False),
    sa.Column('index_value', sa.Numeric(precision=18, scale=4), nullable=False),
    sa.Column('index_change', sa.Numeric(precision=18, scale=4), nullable=False),
    sa.Column('index_change_percent', sa.Numeric(precision=10, scale=4), nullable=False),
    sa.Column('total_volume', sa.Integer(), nullable=False),
    sa.Column('total_value', sa.Numeric(precision=24, scale=4), nullable=False),
    sa.Column('source', sa.String(length=80), nullable=False),
    sa.Column('ingested_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('snapshot_date', 'index_name', 'source', name='uq_market_snapshot_date_index')
    )
    op.create_index('ix_market_snapshots_snapshot_date', 'market_snapshots', ['snapshot_date'], unique=False)
    op.create_table('normalized_events',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('event_type', sa.String(length=60), nullable=False),
    sa.Column('classification_status', sa.String(length=20), nullable=False),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('event_time_end', sa.DateTime(timezone=True), nullable=True),
    sa.Column('cluster_key', sa.String(length=64), nullable=False),
    sa.Column('factor', sa.String(length=80), nullable=True),
    sa.Column('geography', sa.String(length=80), nullable=True),
    sa.Column('magnitude', sa.Numeric(precision=20, scale=6), nullable=True),
    sa.Column('magnitude_unit', sa.String(length=30), nullable=True),
    sa.Column('materiality', sa.String(length=20), nullable=False),
    sa.Column('confidence', sa.Numeric(precision=8, scale=6), nullable=False),
    sa.Column('freshness_score', sa.Numeric(precision=8, scale=6), nullable=False),
    sa.Column('freshness_status', sa.String(length=20), nullable=False),
    sa.Column('detection_version', sa.String(length=40), nullable=False),
    sa.Column('details_json', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('cluster_key', name='uq_normalized_event_cluster_key')
    )
    op.create_index('ix_normalized_event_factor_occurred', 'normalized_events', ['factor', 'occurred_at'], unique=False)
    op.create_index('ix_normalized_event_type_occurred', 'normalized_events', ['event_type', 'occurred_at'], unique=False)
    op.create_index('ix_normalized_events_classification_status', 'normalized_events', ['classification_status'], unique=False)
    op.create_index('ix_normalized_events_event_type', 'normalized_events', ['event_type'], unique=False)
    op.create_index('ix_normalized_events_factor', 'normalized_events', ['factor'], unique=False)
    op.create_index('ix_normalized_events_freshness_status', 'normalized_events', ['freshness_status'], unique=False)
    op.create_index('ix_normalized_events_geography', 'normalized_events', ['geography'], unique=False)
    op.create_index('ix_normalized_events_materiality', 'normalized_events', ['materiality'], unique=False)
    op.create_index('ix_normalized_events_occurred_at', 'normalized_events', ['occurred_at'], unique=False)
    op.create_table('routing_eval_runs',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('run_id', sa.String(length=36), nullable=False),
    sa.Column('eval_case_id', sa.String(length=80), nullable=False),
    sa.Column('router_version', sa.String(length=40), nullable=False),
    sa.Column('mode', sa.String(length=30), nullable=False),
    sa.Column('provider', sa.String(length=50), nullable=True),
    sa.Column('model', sa.String(length=120), nullable=True),
    sa.Column('expected_primary', sa.String(length=40), nullable=False),
    sa.Column('actual_primary', sa.String(length=40), nullable=False),
    sa.Column('expected_secondary_json', sa.Text(), nullable=False),
    sa.Column('actual_secondary_json', sa.Text(), nullable=False),
    sa.Column('decision_source', sa.String(length=30), nullable=False),
    sa.Column('matched', sa.Boolean(), nullable=False),
    sa.Column('errors_json', sa.Text(), nullable=False),
    sa.Column('run_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_routing_eval_runs_run_id', 'routing_eval_runs', ['run_id'], unique=False)
    op.create_table('sector_daily_stats',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('sector', sa.String(length=120), nullable=False),
    sa.Column('trade_date', sa.Date(), nullable=False),
    sa.Column('total_volume', sa.Integer(), nullable=False),
    sa.Column('total_value', sa.Numeric(precision=24, scale=4), nullable=False),
    sa.Column('average_change_percent', sa.Numeric(precision=10, scale=4), nullable=False),
    sa.Column('advancers', sa.Integer(), nullable=False),
    sa.Column('decliners', sa.Integer(), nullable=False),
    sa.Column('unchanged', sa.Integer(), nullable=False),
    sa.Column('source', sa.String(length=80), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('sector', 'trade_date', 'source', name='uq_sector_stats_sector_date_source')
    )
    op.create_index('ix_sector_daily_stats_sector', 'sector_daily_stats', ['sector'], unique=False)
    op.create_index('ix_sector_daily_stats_trade_date', 'sector_daily_stats', ['trade_date'], unique=False)
    op.create_table('service_credentials',
    sa.Column('purpose', sa.String(length=80), nullable=False),
    sa.Column('provider', sa.String(length=40), nullable=False),
    sa.Column('secret_encrypted', sa.Text(), nullable=False),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('purpose')
    )
    op.create_table('users',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('email', sa.String(length=255), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('full_name', sa.String(length=255), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_users_email', 'users', ['email'], unique=1)
    op.create_table('ai_briefs',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('input_hash', sa.String(length=64), nullable=False),
    sa.Column('generated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('scope', sa.String(length=20), nullable=False),
    sa.Column('scope_key', sa.String(length=64), server_default=sa.text("''"), nullable=False),
    sa.Column('provider', sa.String(length=50), nullable=False),
    sa.Column('model', sa.String(length=100), nullable=False),
    sa.Column('status', sa.String(length=20), server_default=sa.text("'running'"), nullable=False),
    sa.Column('brief_json', sa.Text(), nullable=True),
    sa.Column('facts_json', sa.Text(), nullable=True),
    sa.Column('error_code', sa.String(length=60), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'scope', 'scope_key', 'input_hash', name='uq_ai_brief')
    )
    op.create_index('ix_ai_briefs_scope', 'ai_briefs', ['scope'], unique=False)
    op.create_index('ix_ai_briefs_user_id', 'ai_briefs', ['user_id'], unique=False)
    op.create_table('companies',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('symbol', sa.String(length=30), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('sector', sa.String(length=120), nullable=False),
    sa.Column('exchange_id', sa.String(length=36), nullable=False),
    sa.Column('official_website', sa.String(length=500), nullable=True),
    sa.Column('psx_url', sa.String(length=500), nullable=True),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['exchange_id'], ['exchanges.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_companies_sector', 'companies', ['sector'], unique=False)
    op.create_index('ix_companies_symbol', 'companies', ['symbol'], unique=1)
    op.create_table('context_ingestion_work',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('deficiency_id', sa.String(length=36), nullable=False),
    sa.Column('family', sa.String(length=40), nullable=False),
    sa.Column('mode', sa.String(length=40), nullable=False),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('linked_work_json', sa.Text(), nullable=False),
    sa.Column('attempt_count', sa.Integer(), nullable=False),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('requested_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('deadline_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('terminal_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['deficiency_id'], ['context_deficiencies.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('deficiency_id', name='uq_context_ingestion_work_deficiency')
    )
    op.create_index('ix_context_ingestion_work_deficiency_id', 'context_ingestion_work', ['deficiency_id'], unique=False)
    op.create_index('ix_context_ingestion_work_family', 'context_ingestion_work', ['family'], unique=False)
    op.create_index('ix_context_ingestion_work_status', 'context_ingestion_work', ['status'], unique=False)
    op.create_table('enrichment_attempts',
    sa.Column('stage_run_id', sa.String(length=36), nullable=False),
    sa.Column('attempt_number', sa.Integer(), nullable=False),
    sa.Column('provider', sa.String(length=40), nullable=False),
    sa.Column('requested_model', sa.String(length=120), nullable=False),
    sa.Column('actual_model', sa.String(length=120), nullable=True),
    sa.Column('request_hash', sa.String(length=64), nullable=False),
    sa.Column('request_encrypted', sa.Text(), nullable=True),
    sa.Column('response_encrypted', sa.Text(), nullable=True),
    sa.Column('usage', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.Column('error_code', sa.String(length=100), nullable=True),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['stage_run_id'], ['ingestion_stage_runs.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('stage_run_id', 'attempt_number', name='uq_pipeline_enrichment_attempt')
    )
    op.create_table('event_cluster_features',
    sa.Column('event_id', sa.String(length=36), nullable=False),
    sa.Column('entities', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('reporting_period', sa.String(length=40), nullable=True),
    sa.Column('counterparties', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('amounts', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('direction', sa.String(length=20), nullable=False),
    sa.Column('embedding_model', sa.String(length=120), nullable=False),
    sa.Column('embedding', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.ForeignKeyConstraint(['event_id'], ['normalized_events.id'], ),
    sa.PrimaryKeyConstraint('event_id')
    )
    op.create_index('ix_event_cluster_features_reporting_period', 'event_cluster_features', ['reporting_period'], unique=False)
    op.create_table('event_entity_links',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('event_id', sa.String(length=36), nullable=False),
    sa.Column('entity_type', sa.String(length=30), nullable=False),
    sa.Column('entity_key', sa.String(length=160), nullable=False),
    sa.Column('link_method', sa.String(length=30), nullable=False),
    sa.Column('confidence', sa.Numeric(precision=8, scale=6), nullable=False),
    sa.ForeignKeyConstraint(['event_id'], ['events.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_research_event_entity_links_entity_type', 'event_entity_links', ['entity_type', 'entity_key', 'event_id'], unique=False)
    op.create_table('evidence_refresh_requests',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('requested_by_user_id', sa.String(length=36), nullable=True),
    sa.Column('request_type', sa.String(length=20), nullable=False),
    sa.Column('scope_key', sa.String(length=160), nullable=False),
    sa.Column('query_text', sa.String(length=500), nullable=True),
    sa.Column('source_keys_json', sa.Text(), server_default=sa.text('\'["gdelt"]\''), nullable=False),
    sa.Column('status', sa.String(length=20), server_default=sa.text("'queued'"), nullable=False),
    sa.Column('priority_class', sa.String(length=20), server_default=sa.text("'live'"), nullable=False),
    sa.Column('max_candidates', sa.Integer(), nullable=False),
    sa.Column('discovered_count', sa.Integer(), server_default=sa.text("'0'"), nullable=False),
    sa.Column('selected_count', sa.Integer(), server_default=sa.text("'0'"), nullable=False),
    sa.Column('duplicate_count', sa.Integer(), server_default=sa.text("'0'"), nullable=False),
    sa.Column('rejected_count', sa.Integer(), server_default=sa.text("'0'"), nullable=False),
    sa.Column('error_class', sa.String(length=160), nullable=True),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('preset_key', sa.String(length=40), nullable=True),
    sa.Column('date_from', sa.Date(), nullable=True),
    sa.Column('date_to', sa.Date(), nullable=True),
    sa.Column('progress_json', sa.Text(), server_default=sa.text("'{}'"), nullable=False),
    sa.Column('fetch_budget', sa.Integer(), server_default=sa.text("'50'"), nullable=False),
    sa.Column('storage_budget_bytes', sa.BigInteger(), server_default=sa.text("'262144000'"), nullable=False),
    sa.Column('fetched_count', sa.Integer(), server_default=sa.text("'0'"), nullable=False),
    sa.Column('fetched_bytes', sa.BigInteger(), server_default=sa.text("'0'"), nullable=False),
    sa.CheckConstraint("priority_class IN ('live', 'historical')", name='ck_evidence_refresh_priority'),
    sa.CheckConstraint("request_type IN ('targeted', 'historical')", name='ck_evidence_refresh_request_type'),
    sa.CheckConstraint("status IN ('queued', 'running', 'processing', 'complete', 'partial', 'failed')", name='ck_evidence_refresh_status'),
    sa.CheckConstraint('fetch_budget > 0', name='ck_evidence_refresh_fetch_budget_positive'),
    sa.CheckConstraint('max_candidates > 0', name='ck_evidence_refresh_limit_positive'),
    sa.CheckConstraint('storage_budget_bytes > 0', name='ck_evidence_refresh_storage_budget_positive'),
    sa.ForeignKeyConstraint(['requested_by_user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_evidence_refresh_requests_requested_by_user_id', 'evidence_refresh_requests', ['requested_by_user_id'], unique=False)
    op.create_index('ix_evidence_refresh_status_priority', 'evidence_refresh_requests', ['status', 'priority_class', 'created_at'], unique=False)
    op.create_index('ix_evidence_refresh_user_created', 'evidence_refresh_requests', ['requested_by_user_id', 'created_at'], unique=False)
    op.create_table('evidence_source_configs',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('data_source_id', sa.String(length=36), nullable=False),
    sa.Column('source_key', sa.String(length=80), nullable=False),
    sa.Column('source_tier', sa.String(length=30), server_default=sa.text("'other'"), nullable=False),
    sa.Column('roles_json', sa.Text(), server_default=sa.text("'[]'"), nullable=False),
    sa.Column('categories_json', sa.Text(), server_default=sa.text("'[]'"), nullable=False),
    sa.Column('discovery_methods_json', sa.Text(), server_default=sa.text("'[]'"), nullable=False),
    sa.Column('fetch_methods_json', sa.Text(), server_default=sa.text("'[]'"), nullable=False),
    sa.Column('languages_json', sa.Text(), server_default=sa.text('\'["en"]\''), nullable=False),
    sa.Column('poll_interval_seconds', sa.Integer(), nullable=False),
    sa.Column('historical_days', sa.Integer(), nullable=True),
    sa.Column('config_version', sa.String(length=40), server_default=sa.text("'evidence-v1'"), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('canary_group', sa.String(length=40), nullable=True),
    sa.Column('daily_discovery_budget', sa.Integer(), server_default=sa.text("'100'"), nullable=False),
    sa.Column('daily_fetch_budget', sa.Integer(), server_default=sa.text("'15'"), nullable=False),
    sa.Column('daily_selected_budget', sa.Integer(), server_default=sa.text("'5'"), nullable=False),
    sa.Column('daily_storage_budget_bytes', sa.BigInteger(), server_default=sa.text("'104857600'"), nullable=False),
    sa.Column('provenance_json', sa.Text(), server_default=sa.text("'{}'"), nullable=False),
    sa.Column('fallback_json', sa.Text(), server_default=sa.text("'{}'"), nullable=False),
    sa.CheckConstraint('daily_discovery_budget > 0', name='ck_evidence_source_daily_discovery_positive'),
    sa.CheckConstraint('daily_fetch_budget > 0', name='ck_evidence_source_daily_fetch_positive'),
    sa.CheckConstraint('daily_selected_budget > 0', name='ck_evidence_source_daily_selected_positive'),
    sa.CheckConstraint('daily_storage_budget_bytes > 0', name='ck_evidence_source_daily_storage_positive'),
    sa.CheckConstraint('historical_days IS NULL OR historical_days >= 0', name='ck_evidence_source_history_nonnegative'),
    sa.CheckConstraint('poll_interval_seconds > 0', name='ck_evidence_source_poll_positive'),
    sa.ForeignKeyConstraint(['data_source_id'], ['data_sources.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('data_source_id', name='uq_evidence_source_data_source'),
    sa.UniqueConstraint('source_key', name='uq_evidence_source_key')
    )
    op.create_index('ix_evidence_source_configs_canary_group', 'evidence_source_configs', ['canary_group'], unique=False)
    op.create_table('intelligence_context_receipts',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('context_id', sa.String(length=64), nullable=False),
    sa.Column('contract_version', sa.String(length=30), nullable=False),
    sa.Column('content_hash', sa.String(length=64), nullable=False),
    sa.Column('receipt_json', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('consumer_type', sa.String(length=30), nullable=True),
    sa.Column('consumer_key', sa.String(length=160), nullable=True),
    sa.Column('output_id', sa.String(length=36), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_intelligence_context_receipts_consumer_key', 'intelligence_context_receipts', ['consumer_key'], unique=False)
    op.create_index('ix_intelligence_context_receipts_consumer_type', 'intelligence_context_receipts', ['consumer_type'], unique=False)
    op.create_index('ix_intelligence_context_receipts_content_hash', 'intelligence_context_receipts', ['content_hash'], unique=False)
    op.create_index('ix_intelligence_context_receipts_context_id', 'intelligence_context_receipts', ['context_id'], unique=False)
    op.create_index('ix_intelligence_context_receipts_output_id', 'intelligence_context_receipts', ['output_id'], unique=False)
    op.create_index('ix_intelligence_context_receipts_user_id', 'intelligence_context_receipts', ['user_id'], unique=False)
    op.create_table('investor_financial_profile_versions',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('profile_json', sa.Text(), nullable=False),
    sa.Column('confirmed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'version', name='uq_profile_version')
    )
    op.create_table('investor_financial_profiles',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('current_version_id', sa.String(length=36), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id')
    )
    op.create_table('llm_api_keys',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('provider', sa.String(length=50), nullable=False),
    sa.Column('encrypted_api_key', sa.Text(), nullable=False),
    sa.Column('masked_api_key', sa.String(length=64), nullable=False),
    sa.Column('default_model', sa.String(length=100), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_llm_api_keys_user_id', 'llm_api_keys', ['user_id'], unique=False)
    op.create_table('macro_series',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('key', sa.String(length=160), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('unit', sa.String(length=60), nullable=False),
    sa.Column('frequency', sa.String(length=30), nullable=False),
    sa.Column('source_id', sa.String(length=36), nullable=False),
    sa.Column('metadata_json', sa.Text(), nullable=False),
    sa.ForeignKeyConstraint(['source_id'], ['data_sources.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('key')
    )
    op.create_table('normalized_event_evidence',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('normalized_event_id', sa.String(length=36), nullable=False),
    sa.Column('raw_event_id', sa.String(length=36), nullable=False),
    sa.Column('evidence_role', sa.String(length=30), nullable=False),
    sa.Column('linked_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['normalized_event_id'], ['normalized_events.id'], ),
    sa.ForeignKeyConstraint(['raw_event_id'], ['events.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('raw_event_id')
    )
    op.create_index('ix_normalized_event_evidence_normalized_event_id', 'normalized_event_evidence', ['normalized_event_id'], unique=False)
    op.create_index('ix_normalized_event_evidence_raw_event_id', 'normalized_event_evidence', ['raw_event_id'], unique=False)
    op.create_table('normalized_event_subjects',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('normalized_event_id', sa.String(length=36), nullable=False),
    sa.Column('subject_type', sa.String(length=30), nullable=False),
    sa.Column('subject_key', sa.String(length=160), nullable=False),
    sa.Column('link_method', sa.String(length=40), nullable=False),
    sa.Column('confidence', sa.Numeric(precision=8, scale=6), nullable=False),
    sa.Column('is_direct', sa.Boolean(), nullable=False),
    sa.ForeignKeyConstraint(['normalized_event_id'], ['normalized_events.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('normalized_event_id', 'subject_type', 'subject_key', name='uq_normalized_event_subject')
    )
    op.create_index('ix_normalized_event_subjects_normalized_event_id', 'normalized_event_subjects', ['normalized_event_id'], unique=False)
    op.create_index('ix_normalized_event_subjects_subject_key', 'normalized_event_subjects', ['subject_key'], unique=False)
    op.create_index('ix_normalized_event_subjects_subject_type', 'normalized_event_subjects', ['subject_type'], unique=False)
    op.create_index('ix_research_normalized_event_subjects_subject_type', 'normalized_event_subjects', ['subject_type', 'subject_key', 'normalized_event_id'], unique=False)
    op.create_table('portfolios',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('base_currency', sa.String(length=10), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('source_mode', sa.String(length=20), server_default=sa.text("'manual'"), nullable=False),
    sa.Column('provider_name', sa.String(length=80), server_default=sa.text("'ManualPortfolioProvider'"), nullable=False),
    sa.Column('last_synced_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('is_default', sa.Boolean(), server_default=sa.false(), nullable=False),
    sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('history_start', sa.Date(), nullable=True),
    sa.Column('history_complete', sa.Boolean(), server_default=sa.false(), nullable=False),
    sa.Column('goal_summary', sa.Text(), nullable=True),
    sa.Column('benchmark_instrument_id', sa.String(length=36), nullable=True),
    sa.Column('selected_ips_version_id', sa.String(length=36), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_portfolios_user_id', 'portfolios', ['user_id'], unique=False)
    op.create_table('source_artifacts',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('data_source_id', sa.String(length=36), nullable=False),
    sa.Column('source_url', sa.String(length=1000), nullable=False),
    sa.Column('http_method', sa.String(length=10), nullable=False),
    sa.Column('request_fingerprint', sa.String(length=64), nullable=True),
    sa.Column('retrieved_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('source_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('effective_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('content_type', sa.String(length=120), nullable=True),
    sa.Column('storage_path', sa.String(length=1000), nullable=True),
    sa.Column('parser_version', sa.String(length=80), nullable=False),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('response_metadata_json', sa.Text(), nullable=False),
    sa.ForeignKeyConstraint(['data_source_id'], ['data_sources.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('data_source_id', 'request_fingerprint', 'sha256', name='uq_source_artifact_capture')
    )
    op.create_table('user_preferences',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('default_llm_provider', sa.String(length=50), nullable=False),
    sa.Column('risk_tolerance', sa.String(length=30), nullable=False),
    sa.Column('investment_horizon', sa.String(length=30), nullable=False),
    sa.Column('preferred_analysis_mode', sa.String(length=40), nullable=False),
    sa.Column('preferred_sectors', sa.Text(), nullable=False),
    sa.Column('avoided_sectors', sa.Text(), nullable=False),
    sa.Column('notification_preferences', sa.Text(), nullable=False),
    sa.Column('followup_frequency', sa.String(length=30), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id')
    )
    op.create_table('allocation_sets',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('portfolio_id', sa.String(length=36), nullable=False),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('assumptions_json', sa.Text(), nullable=False),
    sa.Column('base_value', sa.Numeric(precision=24, scale=4), nullable=True),
    sa.Column('created_by_user_id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['portfolio_id'], ['portfolios.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('artifact_pins',
    sa.Column('artifact_id', sa.String(length=36), nullable=False),
    sa.Column('consumer_type', sa.String(length=40), nullable=False),
    sa.Column('consumer_id', sa.String(length=160), nullable=False),
    sa.ForeignKeyConstraint(['artifact_id'], ['source_artifacts.id'], ),
    sa.PrimaryKeyConstraint('artifact_id', 'consumer_type', 'consumer_id')
    )
    op.create_table('assistant_conversations',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('portfolio_id', sa.String(length=36), nullable=True),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('summary_failure', sa.String(length=80), nullable=True),
    sa.ForeignKeyConstraint(['portfolio_id'], ['portfolios.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('audit_events',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('portfolio_id', sa.String(length=36), nullable=True),
    sa.Column('event_type', sa.String(length=60), nullable=False),
    sa.Column('entity_type', sa.String(length=60), nullable=False),
    sa.Column('entity_id', sa.String(length=36), nullable=False),
    sa.Column('entity_version', sa.Integer(), nullable=True),
    sa.Column('previous_state_json', sa.Text(), server_default=sa.text("'{}'"), nullable=False),
    sa.Column('new_state_json', sa.Text(), server_default=sa.text("'{}'"), nullable=False),
    sa.Column('data_cutoff', sa.Date(), nullable=True),
    sa.Column('source', sa.String(length=160), nullable=True),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['portfolio_id'], ['portfolios.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_audit_events_created_at', 'audit_events', ['created_at'], unique=False)
    op.create_index('ix_audit_events_entity_id', 'audit_events', ['entity_id'], unique=False)
    op.create_index('ix_audit_events_event_type', 'audit_events', ['event_type'], unique=False)
    op.create_index('ix_audit_events_portfolio_id', 'audit_events', ['portfolio_id'], unique=False)
    op.create_index('ix_audit_events_user_id', 'audit_events', ['user_id'], unique=False)
    op.create_table('data_quality_issues',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('artifact_id', sa.String(length=36), nullable=True),
    sa.Column('observation_id', sa.String(length=36), nullable=True),
    sa.Column('rule', sa.String(length=120), nullable=False),
    sa.Column('severity', sa.String(length=20), nullable=False),
    sa.Column('details_json', sa.Text(), nullable=False),
    sa.Column('resolution', sa.Text(), nullable=True),
    sa.Column('selection_status', sa.String(length=20), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['artifact_id'], ['source_artifacts.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('discovery_candidates',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('source_config_id', sa.String(length=36), nullable=False),
    sa.Column('external_id', sa.String(length=255), nullable=True),
    sa.Column('observed_url', sa.String(length=1000), nullable=False),
    sa.Column('canonical_url', sa.String(length=1000), nullable=True),
    sa.Column('canonical_url_hash', sa.String(length=64), nullable=True),
    sa.Column('headline', sa.String(length=500), nullable=False),
    sa.Column('normalized_headline_hash', sa.String(length=64), nullable=True),
    sa.Column('publisher', sa.String(length=160), nullable=False),
    sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('discovered_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('discovery_method', sa.String(length=40), nullable=False),
    sa.Column('discovery_query', sa.String(length=255), nullable=True),
    sa.Column('topic', sa.String(length=120), nullable=True),
    sa.Column('language', sa.String(length=20), nullable=True),
    sa.Column('status', sa.String(length=30), server_default=sa.text("'discovered'"), nullable=False),
    sa.Column('artifact_id', sa.String(length=36), nullable=True),
    sa.Column('event_id', sa.String(length=36), nullable=True),
    sa.Column('body_sha256', sa.String(length=64), nullable=True),
    sa.Column('simhash', sa.String(length=16), nullable=True),
    sa.Column('relevance_score', sa.Numeric(precision=8, scale=6), nullable=True),
    sa.Column('novelty_score', sa.Numeric(precision=8, scale=6), nullable=True),
    sa.Column('quality_score', sa.Numeric(precision=8, scale=6), nullable=True),
    sa.Column('scoring_reasons_json', sa.Text(), server_default=sa.text("'[]'"), nullable=False),
    sa.Column('metadata_json', sa.Text(), server_default=sa.text("'{}'"), nullable=False),
    sa.Column('configuration_version', sa.String(length=40), server_default=sa.text("'evidence-v1'"), nullable=False),
    sa.Column('parser_version', sa.String(length=80), nullable=True),
    sa.Column('retry_count', sa.Integer(), server_default=sa.text("'0'"), nullable=False),
    sa.Column('next_attempt_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('lease_expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_error_class', sa.String(length=160), nullable=True),
    sa.Column('last_error_message', sa.Text(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('fetch_started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('fetched_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('fetched_bytes', sa.BigInteger(), nullable=True),
    sa.Column('selected_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("status IN ('discovered', 'fetch_ready', 'evaluating', 'clustered', 'selected', 'duplicate', 'rejected', 'failed', 'expired')", name='ck_discovery_candidate_status'),
    sa.CheckConstraint('retry_count >= 0', name='ck_discovery_candidate_retry_nonnegative'),
    sa.ForeignKeyConstraint(['artifact_id'], ['source_artifacts.id'], ),
    sa.ForeignKeyConstraint(['event_id'], ['events.id'], ),
    sa.ForeignKeyConstraint(['source_config_id'], ['evidence_source_configs.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('canonical_url_hash', name='uq_discovery_candidate_canonical_url_hash'),
    sa.UniqueConstraint('source_config_id', 'external_id', name='uq_discovery_candidate_external_id')
    )
    op.create_index('ix_discovery_candidate_artifact', 'discovery_candidates', ['artifact_id'], unique=False)
    op.create_index('ix_discovery_candidate_body_hash', 'discovery_candidates', ['body_sha256'], unique=False)
    op.create_index('ix_discovery_candidate_event', 'discovery_candidates', ['event_id'], unique=False)
    op.create_index('ix_discovery_candidate_fetch_started', 'discovery_candidates', ['fetch_started_at'], unique=False)
    op.create_index('ix_discovery_candidate_headline_hash', 'discovery_candidates', ['normalized_headline_hash'], unique=False)
    op.create_index('ix_discovery_candidate_lease', 'discovery_candidates', ['lease_expires_at'], unique=False)
    op.create_index('ix_discovery_candidate_selected_at', 'discovery_candidates', ['selected_at'], unique=False)
    op.create_index('ix_discovery_candidate_simhash', 'discovery_candidates', ['simhash'], unique=False)
    op.create_index('ix_discovery_candidate_source_published', 'discovery_candidates', ['source_config_id', 'published_at'], unique=False)
    op.create_index('ix_discovery_candidate_status_attempt', 'discovery_candidates', ['status', 'next_attempt_at'], unique=False)
    op.create_index('ix_discovery_candidate_topic_published', 'discovery_candidates', ['topic', 'published_at'], unique=False)
    op.create_table('documents',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('company_id', sa.String(length=36), nullable=True),
    sa.Column('symbol', sa.String(length=30), nullable=True),
    sa.Column('sector', sa.String(length=120), nullable=True),
    sa.Column('document_type', sa.String(length=80), nullable=False),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('fiscal_year', sa.Integer(), nullable=True),
    sa.Column('quarter', sa.String(length=20), nullable=True),
    sa.Column('source_name', sa.String(length=120), nullable=False),
    sa.Column('source_url', sa.String(length=500), nullable=True),
    sa.Column('local_file_path', sa.String(length=500), nullable=True),
    sa.Column('content_hash', sa.String(length=64), nullable=False),
    sa.Column('published_date', sa.Date(), nullable=True),
    sa.Column('downloaded_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('parsed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('status', sa.String(length=40), nullable=False),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('owner_user_id', sa.String(length=36), nullable=True),
    sa.Column('portfolio_id', sa.String(length=36), nullable=True),
    sa.Column('visibility', sa.String(length=20), server_default=sa.text("'public'"), nullable=False),
    sa.Column('extraction_version', sa.String(length=80), nullable=True),
    sa.Column('parser_version', sa.String(length=80), nullable=True),
    sa.Column('artifact_id', sa.String(length=36), nullable=True),
    sa.Column('source_tier', sa.Integer(), server_default=sa.text("'3'"), nullable=False),
    sa.Column('data_status', sa.String(length=30), server_default=sa.text("'observed'"), nullable=False),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_documents_artifact_id', 'documents', ['artifact_id'], unique=False)
    op.create_index('ix_documents_company_id', 'documents', ['company_id'], unique=False)
    op.create_index('ix_documents_content_hash', 'documents', ['content_hash'], unique=False)
    op.create_index('ix_documents_data_status', 'documents', ['data_status'], unique=False)
    op.create_index('ix_documents_document_type', 'documents', ['document_type'], unique=False)
    op.create_index('ix_documents_fiscal_year', 'documents', ['fiscal_year'], unique=False)
    op.create_index('ix_documents_owner_user_id', 'documents', ['owner_user_id'], unique=False)
    op.create_index('ix_documents_portfolio_id', 'documents', ['portfolio_id'], unique=False)
    op.create_index('ix_documents_sector', 'documents', ['sector'], unique=False)
    op.create_index('ix_documents_source_tier', 'documents', ['source_tier'], unique=False)
    op.create_index('ix_documents_status', 'documents', ['status'], unique=False)
    op.create_index('ix_documents_symbol', 'documents', ['symbol'], unique=False)
    op.create_index('ix_documents_visibility', 'documents', ['visibility'], unique=False)
    op.create_table('evidence_source_states',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('source_config_id', sa.String(length=36), nullable=False),
    sa.Column('cursor_json', sa.Text(), server_default=sa.text("'{}'"), nullable=False),
    sa.Column('etag', sa.String(length=255), nullable=True),
    sa.Column('last_modified', sa.String(length=255), nullable=True),
    sa.Column('next_poll_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_attempted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_success_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('consecutive_failures', sa.Integer(), server_default=sa.text("'0'"), nullable=False),
    sa.Column('last_error_class', sa.String(length=160), nullable=True),
    sa.Column('last_error_message', sa.Text(), nullable=True),
    sa.Column('diagnostics_json', sa.Text(), server_default=sa.text("'{}'"), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('healthy_since', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['source_config_id'], ['evidence_source_configs.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('source_config_id', name='uq_evidence_source_state_config')
    )
    op.create_index('ix_evidence_source_state_next_poll', 'evidence_source_states', ['next_poll_at'], unique=False)
    op.create_table('exchange_calendar_days',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('exchange_code', sa.String(length=20), nullable=False),
    sa.Column('session_date', sa.Date(), nullable=False),
    sa.Column('is_session', sa.Boolean(), nullable=False),
    sa.Column('open_time', sa.String(length=10), nullable=True),
    sa.Column('close_time', sa.String(length=10), nullable=True),
    sa.Column('reason', sa.String(length=255), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('artifact_id', sa.String(length=36), nullable=True),
    sa.Column('session_windows', sa.JSON(), nullable=True),
    sa.ForeignKeyConstraint(['artifact_id'], ['source_artifacts.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('exchange_code', 'session_date', name='uq_exchange_calendar_day')
    )
    op.create_index('ix_exchange_calendar_days_artifact_id', 'exchange_calendar_days', ['artifact_id'], unique=False)
    op.create_index('ix_exchange_calendar_days_exchange_code', 'exchange_calendar_days', ['exchange_code'], unique=False)
    op.create_index('ix_exchange_calendar_days_session_date', 'exchange_calendar_days', ['session_date'], unique=False)
    op.create_table('instruments',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('company_id', sa.String(length=36), nullable=True),
    sa.Column('symbol', sa.String(length=30), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('instrument_type', sa.String(length=40), nullable=False),
    sa.Column('currency', sa.String(length=10), nullable=False),
    sa.Column('country', sa.String(length=2), nullable=False),
    sa.Column('sector', sa.String(length=120), nullable=True),
    sa.Column('active_from', sa.Date(), nullable=True),
    sa.Column('active_to', sa.Date(), nullable=True),
    sa.Column('metadata_json', sa.Text(), nullable=False),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('company_id'),
    sa.UniqueConstraint('symbol')
    )
    op.create_index('ix_instruments_symbol', 'instruments', ['symbol'], unique=1)
    op.create_table('macro_series_providers',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('series_id', sa.String(length=36), nullable=False),
    sa.Column('data_source_id', sa.String(length=36), nullable=False),
    sa.Column('provider_key', sa.String(length=160), nullable=False),
    sa.Column('source_series_id', sa.String(length=255), nullable=False),
    sa.Column('priority', sa.Integer(), nullable=False),
    sa.Column('authority', sa.String(length=30), nullable=False),
    sa.Column('retrieval_method', sa.String(length=40), nullable=False),
    sa.Column('enabled', sa.Boolean(), server_default=sa.true(), nullable=False),
    sa.Column('metadata_json', sa.Text(), server_default=sa.text("'{}'"), nullable=False),
    sa.ForeignKeyConstraint(['data_source_id'], ['data_sources.id'], ),
    sa.ForeignKeyConstraint(['series_id'], ['macro_series.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('series_id', 'provider_key', name='uq_macro_series_provider')
    )
    op.create_index('ix_macro_series_providers_data_source_id', 'macro_series_providers', ['data_source_id'], unique=False)
    op.create_index('ix_macro_series_providers_provider_key', 'macro_series_providers', ['provider_key'], unique=False)
    op.create_index('ix_macro_series_providers_series_id', 'macro_series_providers', ['series_id'], unique=False)
    op.create_table('market_prices',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('company_id', sa.String(length=36), nullable=False),
    sa.Column('symbol', sa.String(length=30), nullable=False),
    sa.Column('trade_date', sa.Date(), nullable=False),
    sa.Column('open', sa.Numeric(precision=18, scale=4), nullable=False),
    sa.Column('high', sa.Numeric(precision=18, scale=4), nullable=False),
    sa.Column('low', sa.Numeric(precision=18, scale=4), nullable=False),
    sa.Column('close', sa.Numeric(precision=18, scale=4), nullable=False),
    sa.Column('previous_close', sa.Numeric(precision=18, scale=4), nullable=False),
    sa.Column('change', sa.Numeric(precision=18, scale=4), nullable=False),
    sa.Column('change_percent', sa.Numeric(precision=10, scale=4), nullable=False),
    sa.Column('volume', sa.Integer(), nullable=False),
    sa.Column('value', sa.Numeric(precision=24, scale=4), nullable=False),
    sa.Column('market_cap', sa.Numeric(precision=24, scale=4), nullable=True),
    sa.Column('source', sa.String(length=80), nullable=False),
    sa.Column('source_url', sa.String(length=500), nullable=True),
    sa.Column('ingested_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('symbol', 'trade_date', 'source', name='uq_market_prices_symbol_date_source')
    )
    op.create_index('ix_market_prices_company_id', 'market_prices', ['company_id'], unique=False)
    op.create_index('ix_market_prices_symbol', 'market_prices', ['symbol'], unique=False)
    op.create_index('ix_market_prices_trade_date', 'market_prices', ['trade_date'], unique=False)
    op.create_table('monitoring_rules',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('portfolio_id', sa.String(length=36), nullable=False),
    sa.Column('rule_type', sa.String(length=60), nullable=False),
    sa.Column('threshold_json', sa.Text(), nullable=False),
    sa.Column('deduplication_window_minutes', sa.Integer(), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['portfolio_id'], ['portfolios.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('monitoring_runs',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('portfolio_id', sa.String(length=36), nullable=False),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('evidence_json', sa.Text(), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['portfolio_id'], ['portfolios.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('portfolio_cash_accounts',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('portfolio_id', sa.String(length=36), nullable=False),
    sa.Column('currency', sa.String(length=10), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['portfolio_id'], ['portfolios.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('portfolio_id', 'currency', 'name', name='uq_portfolio_cash_account')
    )
    op.create_table('portfolio_event_snapshots',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('input_hash', sa.String(length=64), nullable=False),
    sa.Column('generated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('portfolio_id', sa.String(length=36), nullable=False),
    sa.Column('calculation_version', sa.String(length=40), nullable=False),
    sa.Column('valuation_as_of', sa.String(length=80), nullable=True),
    sa.Column('payload_json', sa.Text(), nullable=False),
    sa.ForeignKeyConstraint(['portfolio_id'], ['portfolios.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('portfolio_id', 'input_hash', 'calculation_version', name='uq_research_snapshot')
    )
    op.create_index('ix_research_portfolio_event_snapshots_user_id', 'portfolio_event_snapshots', ['user_id', 'portfolio_id'], unique=False)
    op.create_table('portfolio_holdings',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('portfolio_id', sa.String(length=36), nullable=False),
    sa.Column('company_id', sa.String(length=36), nullable=False),
    sa.Column('symbol', sa.String(length=30), nullable=False),
    sa.Column('quantity', sa.Numeric(precision=24, scale=6), nullable=False),
    sa.Column('average_cost', sa.Numeric(precision=18, scale=4), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('instrument_id', sa.String(length=36), nullable=True),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
    sa.ForeignKeyConstraint(['portfolio_id'], ['portfolios.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('portfolio_id', 'symbol', name='uq_portfolio_holding_symbol')
    )
    op.create_index('ix_portfolio_holdings_company_id', 'portfolio_holdings', ['company_id'], unique=False)
    op.create_index('ix_portfolio_holdings_portfolio_id', 'portfolio_holdings', ['portfolio_id'], unique=False)
    op.create_index('ix_portfolio_holdings_symbol', 'portfolio_holdings', ['symbol'], unique=False)
    op.create_table('portfolio_ips_versions',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('portfolio_id', sa.String(length=36), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('constraints_json', sa.Text(), nullable=False),
    sa.Column('required_return', sa.Numeric(precision=12, scale=8), nullable=True),
    sa.Column('confirmed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['portfolio_id'], ['portfolios.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('portfolio_id', 'version', name='uq_ips_version')
    )
    op.create_table('portfolio_transactions',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('portfolio_id', sa.String(length=36), nullable=False),
    sa.Column('company_id', sa.String(length=36), nullable=True),
    sa.Column('symbol', sa.String(length=30), nullable=False),
    sa.Column('transaction_type', sa.String(length=40), nullable=False),
    sa.Column('quantity', sa.Numeric(precision=24, scale=6), nullable=True),
    sa.Column('price', sa.Numeric(precision=18, scale=4), nullable=True),
    sa.Column('amount', sa.Numeric(precision=24, scale=4), nullable=False),
    sa.Column('transaction_date', sa.Date(), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('source', sa.String(length=80), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('currency', sa.String(length=10), server_default=sa.text("'PKR'"), nullable=False),
    sa.Column('fees', sa.Numeric(precision=18, scale=4), server_default=sa.text("'0'"), nullable=False),
    sa.Column('taxes', sa.Numeric(precision=18, scale=4), server_default=sa.text("'0'"), nullable=False),
    sa.Column('settlement_date', sa.Date(), nullable=True),
    sa.Column('external_id', sa.String(length=120), nullable=True),
    sa.Column('reversal_of_id', sa.String(length=36), nullable=True),
    sa.Column('instrument_id', sa.String(length=36), nullable=True),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
    sa.ForeignKeyConstraint(['portfolio_id'], ['portfolios.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_portfolio_transactions_company_id', 'portfolio_transactions', ['company_id'], unique=False)
    op.create_index('ix_portfolio_transactions_portfolio_id', 'portfolio_transactions', ['portfolio_id'], unique=False)
    op.create_index('ix_portfolio_transactions_symbol', 'portfolio_transactions', ['symbol'], unique=False)
    op.create_index('ix_portfolio_transactions_transaction_date', 'portfolio_transactions', ['transaction_date'], unique=False)
    op.create_table('recommendations',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('portfolio_id', sa.String(length=36), nullable=False),
    sa.Column('trigger', sa.String(length=160), nullable=False),
    sa.Column('evidence_json', sa.Text(), nullable=False),
    sa.Column('ips_violation_json', sa.Text(), nullable=False),
    sa.Column('assumptions_json', sa.Text(), nullable=False),
    sa.Column('expected_effect_json', sa.Text(), nullable=False),
    sa.Column('uncertainty_json', sa.Text(), nullable=False),
    sa.Column('freshness_json', sa.Text(), nullable=False),
    sa.Column('message', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['portfolio_id'], ['portfolios.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('scenario_definitions',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('portfolio_id', sa.String(length=36), nullable=True),
    sa.Column('owner_user_id', sa.String(length=36), nullable=True),
    sa.Column('name', sa.String(length=160), nullable=False),
    sa.Column('scenario_type', sa.String(length=30), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('assumptions_json', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['owner_user_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['portfolio_id'], ['portfolios.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('alerts',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('portfolio_id', sa.String(length=36), nullable=False),
    sa.Column('monitoring_run_id', sa.String(length=36), nullable=True),
    sa.Column('deduplication_key', sa.String(length=255), nullable=False),
    sa.Column('alert_type', sa.String(length=60), nullable=False),
    sa.Column('severity', sa.String(length=20), nullable=False),
    sa.Column('message', sa.Text(), nullable=False),
    sa.Column('evidence_json', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('acknowledged_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('acknowledged_by_user_id', sa.String(length=36), nullable=True),
    sa.Column('acknowledgement_note', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['monitoring_run_id'], ['monitoring_runs.id'], ),
    sa.ForeignKeyConstraint(['portfolio_id'], ['portfolios.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('deduplication_key')
    )
    op.create_table('allocation_items',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('allocation_set_id', sa.String(length=36), nullable=False),
    sa.Column('symbol', sa.String(length=30), nullable=False),
    sa.Column('instrument_id', sa.String(length=36), nullable=True),
    sa.Column('is_cash', sa.Boolean(), nullable=False),
    sa.Column('target_weight', sa.Numeric(precision=12, scale=8), nullable=False),
    sa.Column('target_amount', sa.Numeric(precision=24, scale=4), nullable=True),
    sa.Column('target_quantity', sa.Numeric(precision=24, scale=6), nullable=True),
    sa.Column('locked', sa.Boolean(), nullable=False),
    sa.ForeignKeyConstraint(['allocation_set_id'], ['allocation_sets.id'], ),
    sa.ForeignKeyConstraint(['instrument_id'], ['instruments.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('allocation_set_id', 'symbol', name='uq_allocation_symbol')
    )
    op.create_table('analysis_runs',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('portfolio_id', sa.String(length=36), nullable=True),
    sa.Column('instrument_id', sa.String(length=36), nullable=True),
    sa.Column('analysis_type', sa.String(length=60), nullable=False),
    sa.Column('input_fingerprint', sa.String(length=64), nullable=False),
    sa.Column('data_cutoff', sa.Date(), nullable=False),
    sa.Column('estimator_json', sa.Text(), nullable=False),
    sa.Column('code_version', sa.String(length=80), nullable=False),
    sa.Column('result_json', sa.Text(), nullable=False),
    sa.Column('artifact_hashes_json', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['instrument_id'], ['instruments.id'], ),
    sa.ForeignKeyConstraint(['portfolio_id'], ['portfolios.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('input_fingerprint')
    )
    op.create_table('assistant_executions',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('client_request_id', sa.String(length=100), nullable=False),
    sa.Column('request_hash', sa.String(length=64), nullable=False),
    sa.Column('request_encrypted', sa.Text(), nullable=False),
    sa.Column('conversation_id', sa.String(length=36), nullable=False),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('response_json', sa.Text(), nullable=True),
    sa.Column('error_code', sa.String(length=80), nullable=True),
    sa.Column('retry_count', sa.Integer(), server_default=sa.text("'0'"), nullable=False),
    sa.Column('repair_count', sa.Integer(), server_default=sa.text("'0'"), nullable=False),
    sa.Column('revision_count', sa.Integer(), server_default=sa.text("'0'"), nullable=False),
    sa.Column('reserved_input_tokens', sa.Integer(), server_default=sa.text("'0'"), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('heartbeat_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('received_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('transcript_encrypted', sa.Text(), nullable=True),
    sa.Column('event_sequence', sa.Integer(), server_default=sa.text("'0'"), nullable=False),
    sa.Column('policy_json', sa.Text(), server_default=sa.text("'{}'"), nullable=False),
    sa.Column('accounting_json', sa.Text(), server_default=sa.text("'{}'"), nullable=False),
    sa.Column('cancel_requested_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['conversation_id'], ['assistant_conversations.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'client_request_id')
    )
    op.create_index('ix_assistant_executions_status', 'assistant_executions', ['status'], unique=False)
    op.create_index('ix_assistant_executions_user_id', 'assistant_executions', ['user_id'], unique=False)
    op.create_index('uq_assistant_active_conversation', 'assistant_executions', ['conversation_id'], unique=1, sqlite_where=sa.text("status IN ('queued', 'running')"), postgresql_where=sa.text("status IN ('queued', 'running')"))
    op.create_table('assistant_messages',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('conversation_id', sa.String(length=36), nullable=False),
    sa.Column('role', sa.String(length=20), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('evidence_json', sa.Text(), nullable=False),
    sa.Column('tool_trace_json', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('message_kind', sa.String(length=30), server_default=sa.text("'answer'"), nullable=False),
    sa.Column('parent_message_id', sa.String(length=36), nullable=True),
    sa.Column('context_receipt_id', sa.String(length=36), nullable=True),
    sa.Column('context_json', sa.Text(), server_default=sa.text("'{}'"), nullable=False),
    sa.Column('execution_id', sa.String(length=36), nullable=True),
    sa.Column('outcome', sa.String(length=30), nullable=True),
    sa.ForeignKeyConstraint(['context_receipt_id'], ['intelligence_context_receipts.id'], name='fk_assistant_messages_context_receipt'),
    sa.ForeignKeyConstraint(['conversation_id'], ['assistant_conversations.id'], ),
    sa.ForeignKeyConstraint(['parent_message_id'], ['assistant_messages.id'], name='fk_assistant_messages_parent_message'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_assistant_messages_context_receipt_id', 'assistant_messages', ['context_receipt_id'], unique=False)
    op.create_index('ix_assistant_messages_execution_id', 'assistant_messages', ['execution_id'], unique=False)
    op.create_index('ix_assistant_messages_parent_message_id', 'assistant_messages', ['parent_message_id'], unique=False)
    op.create_table('company_digests',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('instrument_id', sa.String(length=36), nullable=False),
    sa.Column('input_hash', sa.String(length=64), nullable=False),
    sa.Column('generated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('prompt_version', sa.String(length=40), nullable=False),
    sa.Column('provider', sa.String(length=50), nullable=False),
    sa.Column('model', sa.String(length=100), nullable=False),
    sa.Column('snapshot_json', sa.Text(), nullable=False),
    sa.Column('brief_json', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['instrument_id'], ['instruments.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'instrument_id', 'input_hash', 'prompt_version', 'provider', 'model', name='uq_company_digest')
    )
    op.create_index('ix_company_digests_instrument_id', 'company_digests', ['instrument_id'], unique=False)
    op.create_index('ix_company_digests_user_id', 'company_digests', ['user_id'], unique=False)
    op.create_table('company_event_briefs',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('input_hash', sa.String(length=64), nullable=False),
    sa.Column('generated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('instrument_id', sa.String(length=36), nullable=False),
    sa.Column('normalized_event_id', sa.String(length=36), nullable=True),
    sa.Column('raw_event_id', sa.String(length=36), nullable=True),
    sa.Column('event_key', sa.String(length=80), nullable=False),
    sa.Column('prompt_version', sa.String(length=40), nullable=False),
    sa.Column('provider', sa.String(length=50), nullable=False),
    sa.Column('model', sa.String(length=100), nullable=False),
    sa.Column('brief_json', sa.Text(), nullable=False),
    sa.Column('evidence_json', sa.Text(), nullable=False),
    sa.ForeignKeyConstraint(['instrument_id'], ['instruments.id'], ),
    sa.ForeignKeyConstraint(['normalized_event_id'], ['normalized_events.id'], ),
    sa.ForeignKeyConstraint(['raw_event_id'], ['events.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'instrument_id', 'event_key', 'input_hash', 'prompt_version', 'provider', 'model', name='uq_research_brief')
    )
    op.create_index('ix_research_company_event_briefs_user_id', 'company_event_briefs', ['user_id', 'instrument_id', 'event_key', 'generated_at'], unique=False)
    op.create_table('company_exposure_profiles',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('input_hash', sa.String(length=64), nullable=False),
    sa.Column('generated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('instrument_id', sa.String(length=36), nullable=False),
    sa.Column('prompt_version', sa.String(length=40), nullable=False),
    sa.Column('provider', sa.String(length=50), nullable=False),
    sa.Column('model', sa.String(length=100), nullable=False),
    sa.Column('relationships_json', sa.Text(), nullable=False),
    sa.Column('evidence_json', sa.Text(), nullable=False),
    sa.Column('coverage_json', sa.Text(), nullable=False),
    sa.ForeignKeyConstraint(['instrument_id'], ['instruments.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'instrument_id', 'input_hash', 'prompt_version', 'provider', 'model', name='uq_research_profile')
    )
    op.create_index('ix_research_company_exposure_profiles_user_id', 'company_exposure_profiles', ['user_id', 'instrument_id', 'generated_at'], unique=False)
    op.create_table('company_intelligence_sections',
    sa.Column('instrument_id', sa.String(length=36), nullable=False),
    sa.Column('section_key', sa.String(length=40), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('input_hash', sa.String(length=64), nullable=False),
    sa.Column('content', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('sources', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('gaps', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('validation_status', sa.String(length=24), nullable=False),
    sa.Column('effective_asof', sa.DateTime(timezone=True), nullable=True),
    sa.Column('is_selected', sa.Boolean(), nullable=False),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['instrument_id'], ['instruments.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('instrument_id', 'section_key', 'input_hash', name='uq_pipeline_intelligence_input')
    )
    op.create_index('ix_pipeline_intelligence_current', 'company_intelligence_sections', ['instrument_id', 'section_key'], unique=1, sqlite_where=sa.text('is_selected = 1'), postgresql_where=sa.text('is_selected'))
    op.create_table('company_screening_snapshots',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('instrument_id', sa.String(length=36), nullable=False),
    sa.Column('as_of_date', sa.Date(), nullable=False),
    sa.Column('sector', sa.String(length=120), nullable=True),
    sa.Column('score', sa.Numeric(precision=10, scale=6), nullable=True),
    sa.Column('sector_percentile', sa.Numeric(precision=10, scale=6), nullable=True),
    sa.Column('completeness', sa.Numeric(precision=10, scale=6), nullable=False),
    sa.Column('screenable', sa.Boolean(), server_default=sa.false(), nullable=False),
    sa.Column('promoted', sa.Boolean(), server_default=sa.false(), nullable=False),
    sa.Column('growth_flag', sa.Boolean(), server_default=sa.false(), nullable=False),
    sa.Column('metrics_json', sa.Text(), server_default=sa.text("'{}'"), nullable=False),
    sa.Column('reasons_json', sa.Text(), server_default=sa.text("'[]'"), nullable=False),
    sa.Column('computed_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['instrument_id'], ['instruments.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('instrument_id', 'as_of_date', name='uq_company_screening_date')
    )
    op.create_index('ix_company_screening_snapshots_as_of_date', 'company_screening_snapshots', ['as_of_date'], unique=False)
    op.create_index('ix_company_screening_snapshots_instrument_id', 'company_screening_snapshots', ['instrument_id'], unique=False)
    op.create_index('ix_company_screening_snapshots_sector', 'company_screening_snapshots', ['sector'], unique=False)
    op.create_table('corporate_actions',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('instrument_id', sa.String(length=36), nullable=False),
    sa.Column('action_type', sa.String(length=40), nullable=False),
    sa.Column('effective_date', sa.Date(), nullable=False),
    sa.Column('ex_date', sa.Date(), nullable=True),
    sa.Column('payment_date', sa.Date(), nullable=True),
    sa.Column('details_json', sa.Text(), nullable=False),
    sa.Column('artifact_id', sa.String(length=36), nullable=True),
    sa.ForeignKeyConstraint(['artifact_id'], ['source_artifacts.id'], ),
    sa.ForeignKeyConstraint(['instrument_id'], ['instruments.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('document_chunks',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('document_id', sa.String(length=36), nullable=False),
    sa.Column('company_id', sa.String(length=36), nullable=True),
    sa.Column('symbol', sa.String(length=30), nullable=True),
    sa.Column('chunk_index', sa.Integer(), nullable=False),
    sa.Column('chunk_text', sa.Text(), nullable=False),
    sa.Column('token_count', sa.Integer(), nullable=False),
    sa.Column('embedding_json', sa.Text(), nullable=False),
    sa.Column('metadata_json', sa.Text(), nullable=False),
    sa.Column('source_url', sa.String(length=500), nullable=True),
    sa.Column('page_number', sa.Integer(), nullable=True),
    sa.Column('section_title', sa.String(length=255), nullable=True),
    sa.Column('embedding_vector', Vector(384).with_variant(sa.Text(), 'sqlite'), nullable=True),
    sa.Column('content_type', sa.String(length=20), server_default=sa.text("'narrative'"), nullable=False),
    sa.Column('embedding_model', sa.String(length=160), server_default=sa.text("'unknown'"), nullable=False),
    sa.Column('embedding_index_version', sa.Integer(), server_default=sa.text("'1'"), nullable=False),
    sa.Column('embedding_status', sa.String(length=20), server_default=sa.text("'indexed'"), nullable=False),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
    sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_document_chunks_company_id', 'document_chunks', ['company_id'], unique=False)
    op.create_index('ix_document_chunks_content_type', 'document_chunks', ['content_type'], unique=False)
    op.create_index('ix_document_chunks_document_id', 'document_chunks', ['document_id'], unique=False)
    op.create_index('ix_document_chunks_embedding_index_version', 'document_chunks', ['embedding_index_version'], unique=False)
    op.create_index('ix_document_chunks_embedding_model', 'document_chunks', ['embedding_model'], unique=False)
    op.create_index('ix_document_chunks_embedding_status', 'document_chunks', ['embedding_status'], unique=False)
    op.create_index('ix_document_chunks_symbol', 'document_chunks', ['symbol'], unique=False)
    op.create_table('document_classifications',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('document_id', sa.String(length=36), nullable=False),
    sa.Column('content_hash', sa.String(length=64), nullable=False),
    sa.Column('classifier_version', sa.String(length=40), nullable=False),
    sa.Column('method', sa.String(length=20), nullable=False),
    sa.Column('model', sa.String(length=120), nullable=True),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.Column('gaps', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('output', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('document_id', 'content_hash', 'classifier_version', name='uq_document_classification')
    )
    op.create_index('ix_document_classifications_document_id', 'document_classifications', ['document_id'], unique=False)
    op.create_table('document_evidence_tags',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('document_id', sa.String(length=36), nullable=False),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('value', sa.String(length=120), nullable=False),
    sa.Column('basis', sa.String(length=40), nullable=False),
    sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('document_id', 'kind', 'value')
    )
    op.create_index('ix_document_evidence_tags_document_id', 'document_evidence_tags', ['document_id'], unique=False)
    op.create_index('ix_document_evidence_tags_lookup', 'document_evidence_tags', ['kind', 'value', 'document_id'], unique=False)
    op.create_table('document_pages',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('document_id', sa.String(length=36), nullable=False),
    sa.Column('page_number', sa.Integer(), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('metadata_json', sa.Text(), nullable=False),
    sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_document_pages_document_id', 'document_pages', ['document_id'], unique=False)
    op.create_index('uq_document_physical_page', 'document_pages', ['document_id', 'page_number'], unique=1)
    op.create_table('document_sections',
    sa.Column('document_id', sa.String(length=36), nullable=False),
    sa.Column('ordinal', sa.Integer(), nullable=False),
    sa.Column('kind', sa.String(length=30), nullable=False),
    sa.Column('heading', sa.Text(), nullable=True),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('page_number', sa.Integer(), nullable=True),
    sa.Column('start_offset', sa.Integer(), nullable=False),
    sa.Column('end_offset', sa.Integer(), nullable=False),
    sa.Column('parser_version', sa.String(length=80), nullable=False),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('document_id', 'parser_version', 'ordinal', name='uq_pipeline_section')
    )
    op.create_index('ix_document_sections_document_id', 'document_sections', ['document_id'], unique=False)
    op.create_table('event_sources',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('event_id', sa.String(length=36), nullable=False),
    sa.Column('source_url', sa.String(length=1000), nullable=False),
    sa.Column('source_name', sa.String(length=120), nullable=False),
    sa.Column('artifact_id', sa.String(length=36), nullable=True),
    sa.Column('document_id', sa.String(length=36), nullable=True),
    sa.Column('candidate_id', sa.String(length=36), nullable=True),
    sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('evidence_role', sa.String(length=30), nullable=True),
    sa.Column('selection_status', sa.String(length=20), server_default=sa.text("'legacy'"), nullable=False),
    sa.Column('relevance_score', sa.Numeric(precision=8, scale=6), nullable=True),
    sa.Column('novelty_score', sa.Numeric(precision=8, scale=6), nullable=True),
    sa.Column('quality_score', sa.Numeric(precision=8, scale=6), nullable=True),
    sa.Column('selection_reasons_json', sa.Text(), server_default=sa.text("'[]'"), nullable=False),
    sa.ForeignKeyConstraint(['artifact_id'], ['source_artifacts.id'], ),
    sa.ForeignKeyConstraint(['candidate_id'], ['discovery_candidates.id'], name='fk_event_source_candidate'),
    sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ),
    sa.ForeignKeyConstraint(['event_id'], ['events.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('candidate_id', name='uq_event_source_candidate'),
    sa.UniqueConstraint('event_id', 'source_url', name='uq_event_source_url')
    )
    op.create_index('ix_event_source_published_at', 'event_sources', ['published_at'], unique=False)
    op.create_index('ix_event_source_selection', 'event_sources', ['event_id', 'selection_status', 'evidence_role'], unique=False)
    op.create_table('evidence_statements',
    sa.Column('document_id', sa.String(length=36), nullable=False),
    sa.Column('subject_type', sa.String(length=30), nullable=False),
    sa.Column('subject_key', sa.String(length=160), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('kind', sa.String(length=30), nullable=False),
    sa.Column('event_type', sa.String(length=50), nullable=True),
    sa.Column('lifecycle', sa.String(length=24), nullable=False),
    sa.Column('topics', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('sentiment', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('typed_value', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('attribution', sa.Text(), nullable=True),
    sa.Column('period_start', sa.DateTime(timezone=True), nullable=True),
    sa.Column('period_end', sa.DateTime(timezone=True), nullable=True),
    sa.Column('accounting_basis', sa.String(length=30), nullable=True),
    sa.Column('method', sa.String(length=30), nullable=False),
    sa.Column('extractor_version', sa.String(length=40), nullable=False),
    sa.Column('fingerprint', sa.String(length=64), nullable=False),
    sa.Column('validation_status', sa.String(length=24), nullable=False),
    sa.Column('supersedes_id', sa.String(length=36), nullable=True),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ),
    sa.ForeignKeyConstraint(['supersedes_id'], ['evidence_statements.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('document_id', 'extractor_version', 'fingerprint', name='uq_pipeline_statement')
    )
    op.create_index('ix_evidence_statements_document_id', 'evidence_statements', ['document_id'], unique=False)
    op.create_index('ix_pipeline_statement_subject', 'evidence_statements', ['subject_key', 'kind', 'validation_status'], unique=False)
    op.create_table('financial_facts',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('instrument_id', sa.String(length=36), nullable=False),
    sa.Column('taxonomy_key', sa.String(length=160), nullable=False),
    sa.Column('period_type', sa.String(length=30), nullable=False),
    sa.Column('period_start', sa.Date(), nullable=True),
    sa.Column('period_end', sa.Date(), nullable=False),
    sa.Column('filing_date', sa.Date(), nullable=True),
    sa.Column('value', sa.Numeric(precision=30, scale=8), nullable=False),
    sa.Column('unit', sa.String(length=40), nullable=False),
    sa.Column('currency', sa.String(length=10), nullable=True),
    sa.Column('consolidated', sa.Boolean(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('document_id', sa.String(length=36), nullable=True),
    sa.Column('page_number', sa.Integer(), nullable=True),
    sa.Column('source_label', sa.String(length=255), nullable=True),
    sa.Column('extraction_method', sa.String(length=80), nullable=True),
    sa.Column('confidence', sa.Numeric(precision=8, scale=6), nullable=True),
    sa.Column('diagnostics_json', sa.Text(), server_default=sa.text("'{}'"), nullable=False),
    sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ),
    sa.ForeignKeyConstraint(['instrument_id'], ['instruments.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_research_financial_facts_instrument_id', 'financial_facts', ['instrument_id', 'period_end'], unique=False)
    op.create_table('ingestion_coverage',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('instrument_id', sa.String(length=36), nullable=False),
    sa.Column('dataset_type', sa.String(length=60), nullable=False),
    sa.Column('period_key', sa.String(length=160), nullable=False),
    sa.Column('status', sa.String(length=30), server_default=sa.text("'missing'"), nullable=False),
    sa.Column('source', sa.String(length=80), nullable=False),
    sa.Column('attempted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('retry_count', sa.Integer(), server_default=sa.text("'0'"), nullable=False),
    sa.Column('item_count', sa.Integer(), server_default=sa.text("'0'"), nullable=False),
    sa.Column('error_class', sa.String(length=160), nullable=True),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('diagnostics_json', sa.Text(), server_default=sa.text("'{}'"), nullable=False),
    sa.ForeignKeyConstraint(['instrument_id'], ['instruments.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('instrument_id', 'dataset_type', 'period_key', 'source', name='uq_ingestion_coverage_key')
    )
    op.create_index('ix_ingestion_coverage_dataset_type', 'ingestion_coverage', ['dataset_type'], unique=False)
    op.create_index('ix_ingestion_coverage_instrument_id', 'ingestion_coverage', ['instrument_id'], unique=False)
    op.create_index('ix_ingestion_coverage_period_key', 'ingestion_coverage', ['period_key'], unique=False)
    op.create_index('ix_ingestion_coverage_source', 'ingestion_coverage', ['source'], unique=False)
    op.create_index('ix_ingestion_coverage_status', 'ingestion_coverage', ['status'], unique=False)
    op.create_table('instrument_aliases',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('instrument_id', sa.String(length=36), nullable=False),
    sa.Column('provider', sa.String(length=80), nullable=False),
    sa.Column('alias', sa.String(length=120), nullable=False),
    sa.Column('valid_from', sa.Date(), nullable=True),
    sa.Column('valid_to', sa.Date(), nullable=True),
    sa.ForeignKeyConstraint(['instrument_id'], ['instruments.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('provider', 'alias', 'valid_from', name='uq_instrument_alias_validity')
    )
    op.create_table('macro_observations',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('series_id', sa.String(length=36), nullable=False),
    sa.Column('effective_date', sa.Date(), nullable=False),
    sa.Column('release_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('value', sa.Numeric(precision=24, scale=8), nullable=False),
    sa.Column('revision', sa.Integer(), nullable=False),
    sa.Column('artifact_id', sa.String(length=36), nullable=True),
    sa.Column('is_selected', sa.Boolean(), nullable=False),
    sa.Column('provider_id', sa.String(length=36), nullable=True),
    sa.Column('source_series_id', sa.String(length=255), nullable=True),
    sa.Column('retrieved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('vintage_date', sa.Date(), nullable=True),
    sa.Column('authority', sa.String(length=30), nullable=True),
    sa.Column('confidence', sa.Numeric(precision=6, scale=5), nullable=True),
    sa.Column('selection_reason', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['artifact_id'], ['source_artifacts.id'], ),
    sa.ForeignKeyConstraint(['provider_id'], ['macro_series_providers.id'], name='fk_macro_observations_provider_id'),
    sa.ForeignKeyConstraint(['series_id'], ['macro_series.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('series_id', 'effective_date', 'provider_id', 'release_at', name='uq_macro_provider_revision')
    )
    op.create_index('ix_macro_observations_provider_id', 'macro_observations', ['provider_id'], unique=False)
    op.create_index('ix_macro_observations_source_series_id', 'macro_observations', ['source_series_id'], unique=False)
    op.create_table('market_observations',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('instrument_id', sa.String(length=36), nullable=True),
    sa.Column('series_key', sa.String(length=160), nullable=True),
    sa.Column('effective_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('frequency', sa.String(length=20), nullable=False),
    sa.Column('values_json', sa.Text(), nullable=False),
    sa.Column('currency', sa.String(length=10), nullable=True),
    sa.Column('unit', sa.String(length=40), nullable=True),
    sa.Column('adjustment_state', sa.String(length=40), nullable=False),
    sa.Column('artifact_id', sa.String(length=36), nullable=False),
    sa.Column('is_selected', sa.Boolean(), nullable=False),
    sa.ForeignKeyConstraint(['artifact_id'], ['source_artifacts.id'], ),
    sa.ForeignKeyConstraint(['instrument_id'], ['instruments.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('instrument_id', 'effective_at', 'frequency', 'artifact_id', name='uq_market_observation_source')
    )
    op.create_table('optimizer_runs',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('portfolio_id', sa.String(length=36), nullable=False),
    sa.Column('objective', sa.String(length=40), nullable=False),
    sa.Column('expected_return_method', sa.String(length=40), nullable=True),
    sa.Column('ips_version_id', sa.String(length=36), nullable=True),
    sa.Column('data_cutoff', sa.Date(), nullable=False),
    sa.Column('bounds_json', sa.Text(), nullable=False),
    sa.Column('solver', sa.String(length=60), nullable=True),
    sa.Column('seed', sa.Integer(), nullable=True),
    sa.Column('input_json', sa.Text(), nullable=False),
    sa.Column('result_json', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('diagnostics_json', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['ips_version_id'], ['portfolio_ips_versions.id'], ),
    sa.ForeignKeyConstraint(['portfolio_id'], ['portfolios.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_optimizer_runs_portfolio_id', 'optimizer_runs', ['portfolio_id'], unique=False)
    op.create_table('portfolio_cash_snapshots',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('cash_account_id', sa.String(length=36), nullable=False),
    sa.Column('snapshot_date', sa.Date(), nullable=False),
    sa.Column('balance', sa.Numeric(precision=24, scale=4), nullable=False),
    sa.Column('source_transaction_id', sa.String(length=36), nullable=True),
    sa.ForeignKeyConstraint(['cash_account_id'], ['portfolio_cash_accounts.id'], ),
    sa.ForeignKeyConstraint(['source_transaction_id'], ['portfolio_transactions.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('cash_account_id', 'snapshot_date', name='uq_cash_snapshot')
    )
    op.create_table('portfolio_ips',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('portfolio_id', sa.String(length=36), nullable=False),
    sa.Column('current_version_id', sa.String(length=36), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['current_version_id'], ['portfolio_ips_versions.id'], ),
    sa.ForeignKeyConstraint(['portfolio_id'], ['portfolios.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('portfolio_id')
    )
    op.create_table('portfolio_position_snapshots',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('portfolio_id', sa.String(length=36), nullable=False),
    sa.Column('instrument_id', sa.String(length=36), nullable=False),
    sa.Column('snapshot_date', sa.Date(), nullable=False),
    sa.Column('quantity', sa.Numeric(precision=24, scale=6), nullable=False),
    sa.Column('average_cost', sa.Numeric(precision=18, scale=4), nullable=False),
    sa.Column('source_transaction_id', sa.String(length=36), nullable=True),
    sa.ForeignKeyConstraint(['instrument_id'], ['instruments.id'], ),
    sa.ForeignKeyConstraint(['portfolio_id'], ['portfolios.id'], ),
    sa.ForeignKeyConstraint(['source_transaction_id'], ['portfolio_transactions.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('portfolio_id', 'instrument_id', 'snapshot_date', name='uq_position_snapshot')
    )
    op.create_table('research_jobs',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('parent_id', sa.String(length=36), nullable=True),
    sa.Column('portfolio_id', sa.String(length=36), nullable=True),
    sa.Column('instrument_id', sa.String(length=36), nullable=True),
    sa.Column('job_type', sa.String(length=30), nullable=False),
    sa.Column('dedup_key', sa.String(length=160), nullable=False),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('request_hash', sa.String(length=64), nullable=False),
    sa.Column('request_encrypted', sa.Text(), nullable=True),
    sa.Column('result_json', sa.Text(), nullable=False),
    sa.Column('max_calls', sa.Integer(), nullable=False),
    sa.Column('reserved_calls', sa.Integer(), nullable=False),
    sa.Column('lease_until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('heartbeat_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('error_code', sa.String(length=80), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['instrument_id'], ['instruments.id'], ),
    sa.ForeignKeyConstraint(['parent_id'], ['research_jobs.id'], ),
    sa.ForeignKeyConstraint(['portfolio_id'], ['portfolios.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'dedup_key', name='uq_research_job_dedup')
    )
    op.create_index('ix_research_research_jobs_status', 'research_jobs', ['status', 'created_at'], unique=False)
    op.create_index('ix_research_research_jobs_user_id', 'research_jobs', ['user_id', 'parent_id'], unique=False)
    op.create_table('scenario_runs',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('portfolio_id', sa.String(length=36), nullable=False),
    sa.Column('scenario_definition_id', sa.String(length=36), nullable=True),
    sa.Column('name', sa.String(length=160), nullable=False),
    sa.Column('shocks_json', sa.Text(), nullable=False),
    sa.Column('result_json', sa.Text(), nullable=False),
    sa.Column('data_cutoff', sa.Date(), nullable=False),
    sa.Column('assumptions_json', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['portfolio_id'], ['portfolios.id'], ),
    sa.ForeignKeyConstraint(['scenario_definition_id'], ['scenario_definitions.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('scenario_shocks',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('scenario_definition_id', sa.String(length=36), nullable=False),
    sa.Column('target_type', sa.String(length=30), nullable=False),
    sa.Column('target_key', sa.String(length=160), nullable=False),
    sa.Column('shock_value', sa.Numeric(precision=14, scale=8), nullable=False),
    sa.Column('unit', sa.String(length=30), nullable=False),
    sa.ForeignKeyConstraint(['scenario_definition_id'], ['scenario_definitions.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('source_targets',
    sa.Column('data_source_id', sa.String(length=36), nullable=False),
    sa.Column('evidence_config_id', sa.String(length=36), nullable=True),
    sa.Column('instrument_id', sa.String(length=36), nullable=True),
    sa.Column('scope_key', sa.String(length=160), nullable=False),
    sa.Column('adapter_key', sa.String(length=80), nullable=False),
    sa.Column('url', sa.Text(), nullable=True),
    sa.Column('schedule', sa.String(length=40), nullable=False),
    sa.Column('cursor', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['data_source_id'], ['data_sources.id'], ),
    sa.ForeignKeyConstraint(['evidence_config_id'], ['evidence_source_configs.id'], ),
    sa.ForeignKeyConstraint(['instrument_id'], ['instruments.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('data_source_id', 'scope_key', name='uq_pipeline_source_scope')
    )
    op.create_table('standardized_financial_facts',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('instrument_id', sa.String(length=36), nullable=False),
    sa.Column('metric', sa.String(length=120), nullable=False),
    sa.Column('period_type', sa.String(length=30), nullable=False),
    sa.Column('period_key', sa.String(length=40), nullable=False),
    sa.Column('period_end', sa.Date(), nullable=True),
    sa.Column('value', sa.Numeric(precision=30, scale=8), nullable=False),
    sa.Column('unit', sa.String(length=40), nullable=False),
    sa.Column('currency', sa.String(length=10), nullable=True),
    sa.Column('classification', sa.String(length=40), server_default=sa.text("'standardized_secondary'"), nullable=False),
    sa.Column('source', sa.String(length=80), nullable=False),
    sa.Column('source_url', sa.String(length=1000), nullable=False),
    sa.Column('retrieved_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('quality_status', sa.String(length=30), server_default=sa.text("'observed'"), nullable=False),
    sa.ForeignKeyConstraint(['instrument_id'], ['instruments.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('instrument_id', 'metric', 'period_type', 'period_key', 'source', name='uq_standardized_fact')
    )
    op.create_index('ix_standardized_financial_facts_instrument_id', 'standardized_financial_facts', ['instrument_id'], unique=False)
    op.create_index('ix_standardized_financial_facts_metric', 'standardized_financial_facts', ['metric'], unique=False)
    op.create_index('ix_standardized_financial_facts_period_end', 'standardized_financial_facts', ['period_end'], unique=False)
    op.create_index('ix_standardized_financial_facts_period_key', 'standardized_financial_facts', ['period_key'], unique=False)
    op.create_table('assistant_attempts',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('execution_id', sa.String(length=36), nullable=False),
    sa.Column('operation', sa.String(length=80), nullable=False),
    sa.Column('provider', sa.String(length=50), nullable=False),
    sa.Column('model', sa.String(length=120), nullable=False),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('metadata_json', sa.Text(), nullable=False),
    sa.Column('payload_encrypted', sa.Text(), nullable=True),
    sa.Column('payload_eviction', sa.String(length=40), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['execution_id'], ['assistant_executions.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_assistant_attempts_execution_id', 'assistant_attempts', ['execution_id'], unique=False)
    op.create_table('assistant_conversation_summaries',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('conversation_id', sa.String(length=36), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('covered_through_message_id', sa.String(length=36), nullable=True),
    sa.Column('content_encrypted', sa.Text(), nullable=False),
    sa.Column('policy_version', sa.String(length=50), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['conversation_id'], ['assistant_conversations.id'], ),
    sa.ForeignKeyConstraint(['covered_through_message_id'], ['assistant_messages.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('conversation_id', 'covered_through_message_id'),
    sa.UniqueConstraint('conversation_id', 'version')
    )
    op.create_index('ix_assistant_conversation_summaries_conversation_id', 'assistant_conversation_summaries', ['conversation_id'], unique=False)
    op.create_table('assistant_execution_events',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('execution_id', sa.String(length=36), nullable=False),
    sa.Column('sequence', sa.Integer(), nullable=False),
    sa.Column('kind', sa.String(length=30), nullable=False),
    sa.Column('payload_encrypted', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['execution_id'], ['assistant_executions.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('execution_id', 'sequence')
    )
    op.create_index('ix_assistant_execution_events_execution_id', 'assistant_execution_events', ['execution_id'], unique=False)
    op.create_table('assistant_stages',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('execution_id', sa.String(length=36), nullable=False),
    sa.Column('operation', sa.String(length=80), nullable=False),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('metadata_json', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['execution_id'], ['assistant_executions.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_assistant_stages_execution_id', 'assistant_stages', ['execution_id'], unique=False)
    op.create_table('citations',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('document_id', sa.String(length=36), nullable=False),
    sa.Column('chunk_id', sa.String(length=36), nullable=True),
    sa.Column('source_name', sa.String(length=120), nullable=False),
    sa.Column('source_url', sa.String(length=500), nullable=True),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('page_number', sa.Integer(), nullable=True),
    sa.Column('quote_snippet', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['chunk_id'], ['document_chunks.id'], ),
    sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_citations_chunk_id', 'citations', ['chunk_id'], unique=False)
    op.create_index('ix_citations_document_id', 'citations', ['document_id'], unique=False)
    op.create_table('context_refresh_requests',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('context_id', sa.String(length=64), nullable=False),
    sa.Column('request_json', sa.Text(), nullable=False),
    sa.Column('deficiency_ids_json', sa.Text(), nullable=False),
    sa.Column('work_json', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('rebuild_count', sa.Integer(), nullable=False),
    sa.Column('needs_rebuild', sa.Boolean(), nullable=False),
    sa.Column('terminal_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('notified_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('consumer_type', sa.String(length=30), nullable=True),
    sa.Column('consumer_key', sa.String(length=160), nullable=True),
    sa.Column('source_message_id', sa.String(length=36), nullable=True),
    sa.ForeignKeyConstraint(['source_message_id'], ['assistant_messages.id'], name='fk_context_refresh_source_message'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_context_refresh_requests_consumer_key', 'context_refresh_requests', ['consumer_key'], unique=False)
    op.create_index('ix_context_refresh_requests_consumer_type', 'context_refresh_requests', ['consumer_type'], unique=False)
    op.create_index('ix_context_refresh_requests_context_id', 'context_refresh_requests', ['context_id'], unique=False)
    op.create_index('ix_context_refresh_requests_source_message_id', 'context_refresh_requests', ['source_message_id'], unique=False)
    op.create_index('ix_context_refresh_requests_status', 'context_refresh_requests', ['status'], unique=False)
    op.create_index('ix_context_refresh_requests_user_id', 'context_refresh_requests', ['user_id'], unique=False)
    op.create_table('document_entity_links',
    sa.Column('document_id', sa.String(length=36), nullable=False),
    sa.Column('instrument_id', sa.String(length=36), nullable=False),
    sa.Column('role', sa.String(length=24), nullable=False),
    sa.Column('method', sa.String(length=40), nullable=False),
    sa.Column('section_id', sa.String(length=36), nullable=True),
    sa.Column('support_quote', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ),
    sa.ForeignKeyConstraint(['instrument_id'], ['instruments.id'], ),
    sa.ForeignKeyConstraint(['section_id'], ['document_sections.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('document_id', 'instrument_id', 'role', name='uq_pipeline_entity_link')
    )
    op.create_index('ix_document_entity_links_instrument_id', 'document_entity_links', ['instrument_id'], unique=False)
    op.create_table('event_document_links',
    sa.Column('event_id', sa.String(length=36), nullable=False),
    sa.Column('document_id', sa.String(length=36), nullable=False),
    sa.Column('statement_id', sa.String(length=36), nullable=False),
    sa.Column('role', sa.String(length=24), nullable=False),
    sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ),
    sa.ForeignKeyConstraint(['event_id'], ['normalized_events.id'], ),
    sa.ForeignKeyConstraint(['statement_id'], ['evidence_statements.id'], ),
    sa.PrimaryKeyConstraint('event_id', 'document_id', 'statement_id')
    )
    op.create_table('intelligence_dependencies',
    sa.Column('section_id', sa.String(length=36), nullable=False),
    sa.Column('dependency_type', sa.String(length=40), nullable=False),
    sa.Column('dependency_id', sa.String(length=160), nullable=False),
    sa.Column('dependency_version', sa.String(length=80), nullable=False),
    sa.ForeignKeyConstraint(['section_id'], ['company_intelligence_sections.id'], ),
    sa.PrimaryKeyConstraint('section_id', 'dependency_type', 'dependency_id')
    )
    op.create_index('ix_pipeline_dependency_reverse', 'intelligence_dependencies', ['dependency_type', 'dependency_id'], unique=False)
    op.create_table('llm_invocations',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('conversation_id', sa.String(length=36), nullable=False),
    sa.Column('assistant_message_id', sa.String(length=36), nullable=False),
    sa.Column('provider', sa.String(length=50), nullable=False),
    sa.Column('model', sa.String(length=120), nullable=False),
    sa.Column('operation', sa.String(length=80), nullable=False),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('http_status', sa.Integer(), nullable=True),
    sa.Column('error_type', sa.String(length=160), nullable=True),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('provider_request_id', sa.String(length=255), nullable=True),
    sa.Column('input_bytes', sa.Integer(), nullable=False),
    sa.Column('input_sha256', sa.String(length=64), nullable=False),
    sa.Column('latency_ms', sa.Integer(), nullable=False),
    sa.Column('input_tokens', sa.Integer(), nullable=True),
    sa.Column('output_tokens', sa.Integer(), nullable=True),
    sa.Column('response_excerpt', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('execution_id', sa.String(length=36), nullable=True),
    sa.ForeignKeyConstraint(['assistant_message_id'], ['assistant_messages.id'], ),
    sa.ForeignKeyConstraint(['conversation_id'], ['assistant_conversations.id'], ),
    sa.ForeignKeyConstraint(['execution_id'], ['assistant_executions.id'], name='fk_llm_invocations_execution_id'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_llm_invocations_assistant_message_id', 'llm_invocations', ['assistant_message_id'], unique=False)
    op.create_index('ix_llm_invocations_conversation_id', 'llm_invocations', ['conversation_id'], unique=False)
    op.create_index('ix_llm_invocations_execution_id', 'llm_invocations', ['execution_id'], unique=False)
    op.create_index('ix_llm_invocations_provider', 'llm_invocations', ['provider'], unique=False)
    op.create_index('ix_llm_invocations_provider_request_id', 'llm_invocations', ['provider_request_id'], unique=False)
    op.create_index('ix_llm_invocations_status', 'llm_invocations', ['status'], unique=False)
    op.create_index('ix_llm_invocations_user_id', 'llm_invocations', ['user_id'], unique=False)
    op.create_table('optimizer_allocations',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('optimizer_run_id', sa.String(length=36), nullable=False),
    sa.Column('instrument_id', sa.String(length=36), nullable=False),
    sa.Column('weight', sa.Numeric(precision=12, scale=8), nullable=False),
    sa.ForeignKeyConstraint(['instrument_id'], ['instruments.id'], ),
    sa.ForeignKeyConstraint(['optimizer_run_id'], ['optimizer_runs.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('optimizer_run_id', 'instrument_id', name='uq_optimizer_instrument')
    )
    op.create_table('research_attempts',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('job_id', sa.String(length=36), nullable=False),
    sa.Column('provider', sa.String(length=50), nullable=False),
    sa.Column('model', sa.String(length=100), nullable=False),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('request_hash', sa.String(length=64), nullable=False),
    sa.Column('request_encrypted', sa.Text(), nullable=True),
    sa.Column('response_encrypted', sa.Text(), nullable=True),
    sa.Column('provider_request_id', sa.String(length=255), nullable=True),
    sa.Column('usage_json', sa.Text(), nullable=False),
    sa.Column('latency_ms', sa.Integer(), nullable=True),
    sa.Column('error_code', sa.String(length=80), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['job_id'], ['research_jobs.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('job_id')
    )
    op.create_table('route_decisions',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('execution_id', sa.String(length=36), nullable=False),
    sa.Column('primary_route', sa.String(length=40), nullable=False),
    sa.Column('secondary_routes_json', sa.Text(), nullable=False),
    sa.Column('decision_source', sa.String(length=30), nullable=False),
    sa.Column('confidence', sa.Float(), nullable=False),
    sa.Column('fallback_used', sa.Boolean(), nullable=False),
    sa.Column('flags_json', sa.Text(), nullable=False),
    sa.Column('scores_json', sa.Text(), nullable=False),
    sa.Column('blocks_json', sa.Text(), nullable=False),
    sa.Column('missing_blocks_json', sa.Text(), nullable=False),
    sa.Column('router_version', sa.String(length=40), nullable=False),
    sa.Column('planner_version', sa.String(length=40), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['execution_id'], ['assistant_executions.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('execution_id')
    )
    op.create_index('ix_route_decisions_created_at', 'route_decisions', ['created_at'], unique=False)
    op.create_index('ix_route_decisions_fallback_used', 'route_decisions', ['fallback_used'], unique=False)
    op.create_index('ix_route_decisions_primary_route', 'route_decisions', ['primary_route'], unique=False)
    op.create_index('ix_route_decisions_user_id', 'route_decisions', ['user_id'], unique=False)
    op.create_table('statement_evidence',
    sa.Column('statement_id', sa.String(length=36), nullable=False),
    sa.Column('section_id', sa.String(length=36), nullable=False),
    sa.Column('quote', sa.Text(), nullable=False),
    sa.Column('start_offset', sa.Integer(), nullable=False),
    sa.Column('end_offset', sa.Integer(), nullable=False),
    sa.Column('locator', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.ForeignKeyConstraint(['section_id'], ['document_sections.id'], ),
    sa.ForeignKeyConstraint(['statement_id'], ['evidence_statements.id'], ),
    sa.PrimaryKeyConstraint('statement_id', 'section_id')
    )
    op.create_table('context_refresh_notifications',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('refresh_request_id', sa.String(length=36), nullable=False),
    sa.Column('receipt_id', sa.String(length=36), nullable=False),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('context_id', sa.String(length=64), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('payload_json', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('delivered_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['receipt_id'], ['intelligence_context_receipts.id'], ),
    sa.ForeignKeyConstraint(['refresh_request_id'], ['context_refresh_requests.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('refresh_request_id', name='uq_context_refresh_notification_request')
    )
    op.create_index('ix_context_refresh_notifications_context_id', 'context_refresh_notifications', ['context_id'], unique=False)
    op.create_index('ix_context_refresh_notifications_receipt_id', 'context_refresh_notifications', ['receipt_id'], unique=False)
    op.create_index('ix_context_refresh_notifications_refresh_request_id', 'context_refresh_notifications', ['refresh_request_id'], unique=False)
    op.create_index('ix_context_refresh_notifications_status', 'context_refresh_notifications', ['status'], unique=False)
    op.create_index('ix_context_refresh_notifications_user_id', 'context_refresh_notifications', ['user_id'], unique=False)
    op.create_table('route_budget_logs',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('route_decision_id', sa.String(length=36), nullable=False),
    sa.Column('cap', sa.Integer(), nullable=False),
    sa.Column('pre_steps', sa.Integer(), nullable=False),
    sa.Column('post_steps', sa.Integer(), nullable=False),
    sa.Column('dropped_json', sa.Text(), nullable=False),
    sa.Column('missing_required_json', sa.Text(), nullable=False),
    sa.ForeignKeyConstraint(['route_decision_id'], ['route_decisions.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('route_decision_id')
    )

    if op.get_bind().dialect.name == "postgresql":
        op.create_index("ix_document_chunks_embedding_vector_hnsw", "document_chunks", ["embedding_vector"],
                        postgresql_using="hnsw", postgresql_ops={"embedding_vector": "vector_cosine_ops"})
        op.execute("CREATE INDEX ix_assistant_history_text ON assistant_messages USING gin (to_tsvector('simple'::regconfig, content))")
        op.execute("ALTER TABLE document_chunks ADD COLUMN search_vector tsvector")
        op.execute('''CREATE FUNCTION pipeline_chunk_search_vector() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
                NEW.search_vector := setweight(to_tsvector('english',coalesce((SELECT title FROM documents WHERE id=NEW.document_id),'')),'A')
                    || setweight(to_tsvector('english',coalesce(NEW.section_title,'')),'B')
                    || setweight(to_tsvector('english',coalesce(NEW.chunk_text,'')),'C');
                RETURN NEW;
            END $$''')
        op.execute('''CREATE TRIGGER pipeline_chunk_search BEFORE INSERT OR UPDATE OF chunk_text,section_title,document_id
            ON document_chunks FOR EACH ROW EXECUTE FUNCTION pipeline_chunk_search_vector()''')
        op.execute('''CREATE FUNCTION pipeline_document_search_vector() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
                UPDATE document_chunks SET chunk_text=chunk_text WHERE document_id=NEW.id;
                RETURN NEW;
            END $$''')
        op.execute('''CREATE TRIGGER pipeline_document_search AFTER UPDATE OF title ON documents
            FOR EACH ROW WHEN (OLD.title IS DISTINCT FROM NEW.title) EXECUTE FUNCTION pipeline_document_search_vector()''')
        op.execute('CREATE INDEX ix_pipeline_chunk_search ON document_chunks USING gin(search_vector)')


def downgrade():
    if context.get_x_argument(as_dictionary=True).get("allow_baseline_drop") != "true":
        raise RuntimeError("Baseline downgrade drops the entire application schema. Use -x allow_baseline_drop=true only for a disposable database or a verified restore.")
    op.drop_table('route_budget_logs')
    op.drop_table('context_refresh_notifications')
    op.drop_table('statement_evidence')
    op.drop_table('route_decisions')
    op.drop_table('research_attempts')
    op.drop_table('optimizer_allocations')
    op.drop_table('llm_invocations')
    op.drop_table('intelligence_dependencies')
    op.drop_table('event_document_links')
    op.drop_table('document_entity_links')
    op.drop_table('context_refresh_requests')
    op.drop_table('citations')
    op.drop_table('assistant_stages')
    op.drop_table('assistant_execution_events')
    op.drop_table('assistant_conversation_summaries')
    op.drop_table('assistant_attempts')
    op.drop_table('standardized_financial_facts')
    op.drop_table('source_targets')
    op.drop_table('scenario_shocks')
    op.drop_table('scenario_runs')
    op.drop_table('research_jobs')
    op.drop_table('portfolio_position_snapshots')
    op.drop_table('portfolio_ips')
    op.drop_table('portfolio_cash_snapshots')
    op.drop_table('optimizer_runs')
    op.drop_table('market_observations')
    op.drop_table('macro_observations')
    op.drop_table('instrument_aliases')
    op.drop_table('ingestion_coverage')
    op.drop_table('financial_facts')
    op.drop_table('evidence_statements')
    op.drop_table('event_sources')
    op.drop_table('document_sections')
    op.drop_table('document_pages')
    op.drop_table('document_evidence_tags')
    op.drop_table('document_classifications')
    op.drop_table('document_chunks')
    op.drop_table('corporate_actions')
    op.drop_table('company_screening_snapshots')
    op.drop_table('company_intelligence_sections')
    op.drop_table('company_exposure_profiles')
    op.drop_table('company_event_briefs')
    op.drop_table('company_digests')
    op.drop_table('assistant_messages')
    op.drop_table('assistant_executions')
    op.drop_table('analysis_runs')
    op.drop_table('allocation_items')
    op.drop_table('alerts')
    op.drop_table('scenario_definitions')
    op.drop_table('recommendations')
    op.drop_table('portfolio_transactions')
    op.drop_table('portfolio_ips_versions')
    op.drop_table('portfolio_holdings')
    op.drop_table('portfolio_event_snapshots')
    op.drop_table('portfolio_cash_accounts')
    op.drop_table('monitoring_runs')
    op.drop_table('monitoring_rules')
    op.drop_table('market_prices')
    op.drop_table('macro_series_providers')
    op.drop_table('instruments')
    op.drop_table('exchange_calendar_days')
    op.drop_table('evidence_source_states')
    op.drop_table('documents')
    op.drop_table('discovery_candidates')
    op.drop_table('data_quality_issues')
    op.drop_table('audit_events')
    op.drop_table('assistant_conversations')
    op.drop_table('artifact_pins')
    op.drop_table('allocation_sets')
    op.drop_table('user_preferences')
    op.drop_table('source_artifacts')
    op.drop_table('portfolios')
    op.drop_table('normalized_event_subjects')
    op.drop_table('normalized_event_evidence')
    op.drop_table('macro_series')
    op.drop_table('llm_api_keys')
    op.drop_table('investor_financial_profiles')
    op.drop_table('investor_financial_profile_versions')
    op.drop_table('intelligence_context_receipts')
    op.drop_table('evidence_source_configs')
    op.drop_table('evidence_refresh_requests')
    op.drop_table('event_entity_links')
    op.drop_table('event_cluster_features')
    op.drop_table('enrichment_attempts')
    op.drop_table('context_ingestion_work')
    op.drop_table('companies')
    op.drop_table('ai_briefs')
    op.drop_table('users')
    op.drop_table('service_credentials')
    op.drop_table('sector_daily_stats')
    op.drop_table('routing_eval_runs')
    op.drop_table('normalized_events')
    op.drop_table('market_snapshots')
    op.drop_table('market_ingestion_runs')
    op.drop_table('ingestion_stage_runs')
    op.drop_table('ingestion_runs')
    op.drop_table('exchanges')
    op.drop_table('events')
    op.drop_table('data_sources')
    op.drop_table('context_deficiencies')
    op.drop_table('company_marks')
    op.drop_table('assistant_provider_queue')
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP FUNCTION pipeline_document_search_vector()")
        op.execute("DROP FUNCTION pipeline_chunk_search_vector()")
