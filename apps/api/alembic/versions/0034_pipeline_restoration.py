"""Durable public evidence stages and source-linked company intelligence."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision = '0034_pipeline_restoration'
down_revision = '0033_company_digests'
branch_labels = depends_on = None

def upgrade():
    op.add_column("exchange_calendar_days", sa.Column("session_windows", sa.JSON(), nullable=True))
    op.create_table('source_targets',
        sa.Column('data_source_id', sa.String(36), sa.ForeignKey('data_sources.id'), primary_key=False, nullable=False),
        sa.Column('evidence_config_id', sa.String(36), sa.ForeignKey('evidence_source_configs.id'), primary_key=False, nullable=True),
        sa.Column('instrument_id', sa.String(36), sa.ForeignKey('instruments.id'), primary_key=False, nullable=True),
        sa.Column('scope_key', sa.String(160), primary_key=False, nullable=False),
        sa.Column('adapter_key', sa.String(80), primary_key=False, nullable=False),
        sa.Column('url', sa.Text(), primary_key=False, nullable=True),
        sa.Column('schedule', sa.String(40), primary_key=False, nullable=False),
        sa.Column('cursor', sa.JSON().with_variant(postgresql.JSONB(), 'postgresql'), primary_key=False, nullable=False),
        sa.Column('enabled', sa.Boolean(), primary_key=False, nullable=False),
        sa.Column('id', sa.String(36), primary_key=True, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), primary_key=False, nullable=False),
        sa.UniqueConstraint('data_source_id', 'scope_key', name='uq_pipeline_source_scope'),
    )
    op.create_table('ingestion_stage_runs',
        sa.Column('stage', sa.String(40), primary_key=False, nullable=False),
        sa.Column('subject_key', sa.String(160), primary_key=False, nullable=False),
        sa.Column('input_hash', sa.String(64), primary_key=False, nullable=False),
        sa.Column('code_version', sa.String(40), primary_key=False, nullable=False),
        sa.Column('mode', sa.String(20), primary_key=False, nullable=False),
        sa.Column('input', sa.JSON().with_variant(postgresql.JSONB(), 'postgresql'), primary_key=False, nullable=False),
        sa.Column('output', sa.JSON().with_variant(postgresql.JSONB(), 'postgresql'), primary_key=False, nullable=False),
        sa.Column('status', sa.String(24), primary_key=False, nullable=False),
        sa.Column('attempt_count', sa.Integer(), primary_key=False, nullable=False),
        sa.Column('lease_token', sa.String(36), primary_key=False, nullable=True),
        sa.Column('lease_until', sa.DateTime(timezone=True), primary_key=False, nullable=True),
        sa.Column('heartbeat_at', sa.DateTime(timezone=True), primary_key=False, nullable=True),
        sa.Column('next_attempt_at', sa.DateTime(timezone=True), primary_key=False, nullable=True),
        sa.Column('dispatch_until', sa.DateTime(timezone=True), primary_key=False, nullable=True),
        sa.Column('error_code', sa.String(100), primary_key=False, nullable=True),
        sa.Column('finished_at', sa.DateTime(timezone=True), primary_key=False, nullable=True),
        sa.Column('id', sa.String(36), primary_key=True, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), primary_key=False, nullable=False),
        sa.UniqueConstraint('stage', 'subject_key', 'input_hash', 'code_version', name='uq_pipeline_stage_input'),
    )
    op.create_index('ix_pipeline_dispatch', 'ingestion_stage_runs', ['status', 'next_attempt_at', 'mode'], unique=False)
    op.create_index('ix_pipeline_lease', 'ingestion_stage_runs', ['status', 'lease_until'], unique=False)
    op.create_table('document_sections',
        sa.Column('document_id', sa.String(36), sa.ForeignKey('documents.id'), primary_key=False, nullable=False),
        sa.Column('ordinal', sa.Integer(), primary_key=False, nullable=False),
        sa.Column('kind', sa.String(30), primary_key=False, nullable=False),
        sa.Column('heading', sa.Text(), primary_key=False, nullable=True),
        sa.Column('text', sa.Text(), primary_key=False, nullable=False),
        sa.Column('page_number', sa.Integer(), primary_key=False, nullable=True),
        sa.Column('start_offset', sa.Integer(), primary_key=False, nullable=False),
        sa.Column('end_offset', sa.Integer(), primary_key=False, nullable=False),
        sa.Column('parser_version', sa.String(80), primary_key=False, nullable=False),
        sa.Column('id', sa.String(36), primary_key=True, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), primary_key=False, nullable=False),
        sa.UniqueConstraint('document_id', 'parser_version', 'ordinal', name='uq_pipeline_section'),
    )
    op.create_index('ix_document_sections_document_id', 'document_sections', ['document_id'], unique=False)
    op.create_table('document_entity_links',
        sa.Column('document_id', sa.String(36), sa.ForeignKey('documents.id'), primary_key=False, nullable=False),
        sa.Column('instrument_id', sa.String(36), sa.ForeignKey('instruments.id'), primary_key=False, nullable=False),
        sa.Column('role', sa.String(24), primary_key=False, nullable=False),
        sa.Column('method', sa.String(40), primary_key=False, nullable=False),
        sa.Column('section_id', sa.String(36), sa.ForeignKey('document_sections.id'), primary_key=False, nullable=True),
        sa.Column('support_quote', sa.Text(), primary_key=False, nullable=False),
        sa.Column('status', sa.String(24), primary_key=False, nullable=False),
        sa.Column('id', sa.String(36), primary_key=True, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), primary_key=False, nullable=False),
        sa.UniqueConstraint('document_id', 'instrument_id', 'role', name='uq_pipeline_entity_link'),
    )
    op.create_index('ix_document_entity_links_instrument_id', 'document_entity_links', ['instrument_id'], unique=False)
    op.create_table('evidence_statements',
        sa.Column('document_id', sa.String(36), sa.ForeignKey('documents.id'), primary_key=False, nullable=False),
        sa.Column('subject_type', sa.String(30), primary_key=False, nullable=False),
        sa.Column('subject_key', sa.String(160), primary_key=False, nullable=False),
        sa.Column('text', sa.Text(), primary_key=False, nullable=False),
        sa.Column('kind', sa.String(30), primary_key=False, nullable=False),
        sa.Column('event_type', sa.String(50), primary_key=False, nullable=True),
        sa.Column('lifecycle', sa.String(24), primary_key=False, nullable=False),
        sa.Column('topics', sa.JSON().with_variant(postgresql.JSONB(), 'postgresql'), primary_key=False, nullable=False),
        sa.Column('sentiment', sa.JSON().with_variant(postgresql.JSONB(), 'postgresql'), primary_key=False, nullable=False),
        sa.Column('typed_value', sa.JSON().with_variant(postgresql.JSONB(), 'postgresql'), primary_key=False, nullable=False),
        sa.Column('attribution', sa.Text(), primary_key=False, nullable=True),
        sa.Column('period_start', sa.DateTime(timezone=True), primary_key=False, nullable=True),
        sa.Column('period_end', sa.DateTime(timezone=True), primary_key=False, nullable=True),
        sa.Column('accounting_basis', sa.String(30), primary_key=False, nullable=True),
        sa.Column('method', sa.String(30), primary_key=False, nullable=False),
        sa.Column('extractor_version', sa.String(40), primary_key=False, nullable=False),
        sa.Column('fingerprint', sa.String(64), primary_key=False, nullable=False),
        sa.Column('validation_status', sa.String(24), primary_key=False, nullable=False),
        sa.Column('supersedes_id', sa.String(36), sa.ForeignKey('evidence_statements.id'), primary_key=False, nullable=True),
        sa.Column('id', sa.String(36), primary_key=True, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), primary_key=False, nullable=False),
        sa.UniqueConstraint('document_id', 'extractor_version', 'fingerprint', name='uq_pipeline_statement'),
    )
    op.create_index('ix_evidence_statements_document_id', 'evidence_statements', ['document_id'], unique=False)
    op.create_index('ix_pipeline_statement_subject', 'evidence_statements', ['subject_key', 'kind', 'validation_status'], unique=False)
    op.create_table('statement_evidence',
        sa.Column('statement_id', sa.String(36), sa.ForeignKey('evidence_statements.id'), primary_key=True, nullable=False),
        sa.Column('section_id', sa.String(36), sa.ForeignKey('document_sections.id'), primary_key=True, nullable=False),
        sa.Column('quote', sa.Text(), primary_key=False, nullable=False),
        sa.Column('start_offset', sa.Integer(), primary_key=False, nullable=False),
        sa.Column('end_offset', sa.Integer(), primary_key=False, nullable=False),
        sa.Column('locator', sa.JSON().with_variant(postgresql.JSONB(), 'postgresql'), primary_key=False, nullable=False),
    )
    op.create_table('event_document_links',
        sa.Column('event_id', sa.String(36), sa.ForeignKey('normalized_events.id'), primary_key=True, nullable=False),
        sa.Column('document_id', sa.String(36), sa.ForeignKey('documents.id'), primary_key=True, nullable=False),
        sa.Column('statement_id', sa.String(36), sa.ForeignKey('evidence_statements.id'), primary_key=True, nullable=False),
        sa.Column('role', sa.String(24), primary_key=False, nullable=False),
    )
    op.create_table('company_intelligence_sections',
        sa.Column('instrument_id', sa.String(36), sa.ForeignKey('instruments.id'), primary_key=False, nullable=False),
        sa.Column('section_key', sa.String(40), primary_key=False, nullable=False),
        sa.Column('version', sa.Integer(), primary_key=False, nullable=False),
        sa.Column('input_hash', sa.String(64), primary_key=False, nullable=False),
        sa.Column('content', sa.JSON().with_variant(postgresql.JSONB(), 'postgresql'), primary_key=False, nullable=False),
        sa.Column('sources', sa.JSON().with_variant(postgresql.JSONB(), 'postgresql'), primary_key=False, nullable=False),
        sa.Column('gaps', sa.JSON().with_variant(postgresql.JSONB(), 'postgresql'), primary_key=False, nullable=False),
        sa.Column('validation_status', sa.String(24), primary_key=False, nullable=False),
        sa.Column('effective_asof', sa.DateTime(timezone=True), primary_key=False, nullable=True),
        sa.Column('is_selected', sa.Boolean(), primary_key=False, nullable=False),
        sa.Column('id', sa.String(36), primary_key=True, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), primary_key=False, nullable=False),
        sa.UniqueConstraint('instrument_id', 'section_key', 'input_hash', name='uq_pipeline_intelligence_input'),
    )
    op.create_index('ix_pipeline_intelligence_current', 'company_intelligence_sections', ['instrument_id', 'section_key'], unique=True, postgresql_where=sa.text('is_selected'), sqlite_where=sa.text('is_selected = 1'))
    op.create_table('intelligence_dependencies',
        sa.Column('section_id', sa.String(36), sa.ForeignKey('company_intelligence_sections.id'), primary_key=True, nullable=False),
        sa.Column('dependency_type', sa.String(40), primary_key=True, nullable=False),
        sa.Column('dependency_id', sa.String(160), primary_key=True, nullable=False),
        sa.Column('dependency_version', sa.String(80), primary_key=False, nullable=False),
    )
    op.create_index('ix_pipeline_dependency_reverse', 'intelligence_dependencies', ['dependency_type', 'dependency_id'], unique=False)
    op.create_table('enrichment_attempts',
        sa.Column('stage_run_id', sa.String(36), sa.ForeignKey('ingestion_stage_runs.id'), primary_key=False, nullable=False),
        sa.Column('attempt_number', sa.Integer(), primary_key=False, nullable=False),
        sa.Column('provider', sa.String(40), primary_key=False, nullable=False),
        sa.Column('requested_model', sa.String(120), primary_key=False, nullable=False),
        sa.Column('actual_model', sa.String(120), primary_key=False, nullable=True),
        sa.Column('request_hash', sa.String(64), primary_key=False, nullable=False),
        sa.Column('request_encrypted', sa.Text(), primary_key=False, nullable=True),
        sa.Column('response_encrypted', sa.Text(), primary_key=False, nullable=True),
        sa.Column('usage', sa.JSON().with_variant(postgresql.JSONB(), 'postgresql'), primary_key=False, nullable=False),
        sa.Column('status', sa.String(24), primary_key=False, nullable=False),
        sa.Column('error_code', sa.String(100), primary_key=False, nullable=True),
        sa.Column('id', sa.String(36), primary_key=True, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), primary_key=False, nullable=False),
        sa.UniqueConstraint('stage_run_id', 'attempt_number', name='uq_pipeline_enrichment_attempt'),
    )
    op.create_table('service_credentials',
        sa.Column('purpose', sa.String(80), primary_key=False, nullable=False),
        sa.Column('provider', sa.String(40), primary_key=False, nullable=False),
        sa.Column('secret_encrypted', sa.Text(), primary_key=False, nullable=False),
        sa.Column('active', sa.Boolean(), primary_key=False, nullable=False),
        sa.Column('id', sa.String(36), primary_key=True, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), primary_key=False, nullable=False),
        sa.UniqueConstraint('purpose', name=None),
    )
    op.create_table('artifact_pins',
        sa.Column('artifact_id', sa.String(36), sa.ForeignKey('source_artifacts.id'), primary_key=True, nullable=False),
        sa.Column('consumer_type', sa.String(40), primary_key=True, nullable=False),
        sa.Column('consumer_id', sa.String(160), primary_key=True, nullable=False),
    )

def downgrade():
    op.drop_column("exchange_calendar_days", "session_windows")
    op.drop_table('artifact_pins')
    op.drop_table('service_credentials')
    op.drop_table('enrichment_attempts')
    op.drop_table('intelligence_dependencies')
    op.drop_table('company_intelligence_sections')
    op.drop_table('event_document_links')
    op.drop_table('statement_evidence')
    op.drop_table('evidence_statements')
    op.drop_table('document_entity_links')
    op.drop_table('document_sections')
    op.drop_table('ingestion_stage_runs')
    op.drop_table('source_targets')
