"""Public evidence processing ledger. Private portfolio data never enters these rows."""
from datetime import UTC, datetime
from uuid import uuid4
from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.db.session import Base

JSON_TYPE = JSON().with_variant(JSONB(), 'postgresql')

class Identified:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)

class SourceTarget(Identified, Base):
    __tablename__ = 'source_targets'
    __table_args__ = (UniqueConstraint('data_source_id', 'scope_key', name='uq_pipeline_source_scope'),)
    data_source_id: Mapped[str] = mapped_column(ForeignKey('data_sources.id'), nullable=False)
    evidence_config_id: Mapped[str | None] = mapped_column(ForeignKey('evidence_source_configs.id'))
    instrument_id: Mapped[str | None] = mapped_column(ForeignKey('instruments.id'))
    scope_key: Mapped[str] = mapped_column(String(160), nullable=False)
    adapter_key: Mapped[str] = mapped_column(String(80), nullable=False)
    url: Mapped[str | None] = mapped_column(Text)
    schedule: Mapped[str] = mapped_column(String(40), nullable=False)
    cursor: Mapped[dict] = mapped_column(JSON_TYPE, default=dict, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

class IngestionStageRun(Identified, Base):
    __tablename__ = 'ingestion_stage_runs'
    __table_args__ = (
        UniqueConstraint('stage', 'subject_key', 'input_hash', 'code_version', name='uq_pipeline_stage_input'),
        Index('ix_pipeline_dispatch', 'status', 'next_attempt_at', 'mode'),
        Index('ix_pipeline_lease', 'status', 'lease_until'),
    )
    stage: Mapped[str] = mapped_column(String(40), nullable=False)
    subject_key: Mapped[str] = mapped_column(String(160), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    code_version: Mapped[str] = mapped_column(String(40), nullable=False)
    mode: Mapped[str] = mapped_column(String(20), default='live', nullable=False)
    input: Mapped[dict] = mapped_column(JSON_TYPE, default=dict, nullable=False)
    output: Mapped[dict] = mapped_column(JSON_TYPE, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default='queued', nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    lease_token: Mapped[str | None] = mapped_column(String(36))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dispatch_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(100))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

class DocumentSection(Identified, Base):
    __tablename__ = 'document_sections'
    __table_args__ = (UniqueConstraint('document_id','parser_version','ordinal',name='uq_pipeline_section'),)
    document_id: Mapped[str] = mapped_column(ForeignKey('documents.id'), nullable=False, index=True)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(30), default='paragraph', nullable=False)
    heading: Mapped[str | None] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer)
    start_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    end_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    parser_version: Mapped[str] = mapped_column(String(80), nullable=False)

class DocumentEntityLink(Identified, Base):
    __tablename__ = 'document_entity_links'
    __table_args__ = (UniqueConstraint('document_id','instrument_id','role',name='uq_pipeline_entity_link'),)
    document_id: Mapped[str] = mapped_column(ForeignKey('documents.id'), nullable=False)
    instrument_id: Mapped[str] = mapped_column(ForeignKey('instruments.id'), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(24), default='mentioned', nullable=False)
    method: Mapped[str] = mapped_column(String(40), nullable=False)
    section_id: Mapped[str | None] = mapped_column(ForeignKey('document_sections.id'))
    support_quote: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default='validated', nullable=False)

class EvidenceStatement(Identified, Base):
    __tablename__ = 'evidence_statements'
    __table_args__ = (
        UniqueConstraint('document_id','extractor_version','fingerprint',name='uq_pipeline_statement'),
        Index('ix_pipeline_statement_subject', 'subject_key','kind','validation_status'),
    )
    document_id: Mapped[str] = mapped_column(ForeignKey('documents.id'), nullable=False, index=True)
    subject_type: Mapped[str] = mapped_column(String(30), nullable=False)
    subject_key: Mapped[str] = mapped_column(String(160), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    event_type: Mapped[str | None] = mapped_column(String(50))
    lifecycle: Mapped[str] = mapped_column(String(24), default='unknown', nullable=False)
    topics: Mapped[list] = mapped_column(JSON_TYPE, default=list, nullable=False)
    sentiment: Mapped[dict] = mapped_column(JSON_TYPE, default=dict, nullable=False)
    typed_value: Mapped[dict] = mapped_column(JSON_TYPE, default=dict, nullable=False)
    attribution: Mapped[str | None] = mapped_column(Text)
    period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accounting_basis: Mapped[str | None] = mapped_column(String(30))
    method: Mapped[str] = mapped_column(String(30), nullable=False)
    extractor_version: Mapped[str] = mapped_column(String(40), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    validation_status: Mapped[str] = mapped_column(String(24), default='needs_review', nullable=False)
    supersedes_id: Mapped[str | None] = mapped_column(ForeignKey('evidence_statements.id'))

class StatementEvidence(Base):
    __tablename__ = 'statement_evidence'
    statement_id: Mapped[str] = mapped_column(ForeignKey('evidence_statements.id'), primary_key=True)
    section_id: Mapped[str] = mapped_column(ForeignKey('document_sections.id'), primary_key=True)
    quote: Mapped[str] = mapped_column(Text, nullable=False)
    start_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    end_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    locator: Mapped[dict] = mapped_column(JSON_TYPE, default=dict, nullable=False)

class EventDocumentLink(Base):
    __tablename__ = 'event_document_links'
    event_id: Mapped[str] = mapped_column(ForeignKey('normalized_events.id'), primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey('documents.id'), primary_key=True)
    statement_id: Mapped[str] = mapped_column(ForeignKey('evidence_statements.id'), primary_key=True)
    role: Mapped[str] = mapped_column(String(24), nullable=False)

class CompanyIntelligenceSection(Identified, Base):
    __tablename__ = 'company_intelligence_sections'
    __table_args__ = (
        UniqueConstraint('instrument_id','section_key','input_hash',name='uq_pipeline_intelligence_input'),
        Index('ix_pipeline_intelligence_current','instrument_id','section_key', unique=True,
              postgresql_where=text('is_selected'),
              sqlite_where=text('is_selected = 1')),
    )
    instrument_id: Mapped[str] = mapped_column(ForeignKey('instruments.id'), nullable=False)
    section_key: Mapped[str] = mapped_column(String(40), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    content: Mapped[dict] = mapped_column(JSON_TYPE, default=dict, nullable=False)
    sources: Mapped[list] = mapped_column(JSON_TYPE, default=list, nullable=False)
    gaps: Mapped[list] = mapped_column(JSON_TYPE, default=list, nullable=False)
    validation_status: Mapped[str] = mapped_column(String(24), nullable=False)
    effective_asof: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_selected: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

class IntelligenceDependency(Base):
    __tablename__ = 'intelligence_dependencies'
    __table_args__ = (Index('ix_pipeline_dependency_reverse','dependency_type','dependency_id'),)
    section_id: Mapped[str] = mapped_column(ForeignKey('company_intelligence_sections.id'), primary_key=True)
    dependency_type: Mapped[str] = mapped_column(String(40), primary_key=True)
    dependency_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    dependency_version: Mapped[str] = mapped_column(String(80), nullable=False)

class EnrichmentAttempt(Identified, Base):
    __tablename__ = 'enrichment_attempts'
    __table_args__ = (UniqueConstraint('stage_run_id','attempt_number',name='uq_pipeline_enrichment_attempt'),)
    stage_run_id: Mapped[str] = mapped_column(ForeignKey('ingestion_stage_runs.id'), nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    requested_model: Mapped[str] = mapped_column(String(120), nullable=False)
    actual_model: Mapped[str | None] = mapped_column(String(120))
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_encrypted: Mapped[str | None] = mapped_column(Text)
    response_encrypted: Mapped[str | None] = mapped_column(Text)
    usage: Mapped[dict] = mapped_column(JSON_TYPE, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(100))

class ServiceCredential(Identified, Base):
    __tablename__ = 'service_credentials'
    purpose: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    secret_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

class ArtifactPin(Base):
    __tablename__ = 'artifact_pins'
    artifact_id: Mapped[str] = mapped_column(ForeignKey('source_artifacts.id'), primary_key=True)
    consumer_type: Mapped[str] = mapped_column(String(40), primary_key=True)
    consumer_id: Mapped[str] = mapped_column(String(160), primary_key=True)
