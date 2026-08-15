from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    BigInteger,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.ingestion.evidence import CandidateStatus


def uuid_str() -> str:
    return str(uuid4())


def utcnow() -> datetime:
    return datetime.now(UTC)


class EvidenceSourceConfig(Base):
    __tablename__ = "evidence_source_configs"
    __table_args__ = (
        CheckConstraint("poll_interval_seconds > 0", name="ck_evidence_source_poll_positive"),
        CheckConstraint(
            "historical_days IS NULL OR historical_days >= 0",
            name="ck_evidence_source_history_nonnegative",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    data_source_id: Mapped[str] = mapped_column(
        ForeignKey("data_sources.id"), unique=True, nullable=False
    )
    source_key: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    source_tier: Mapped[str] = mapped_column(String(30), default="other", nullable=False)
    roles_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    categories_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    discovery_methods_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    fetch_methods_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    languages_json: Mapped[str] = mapped_column(Text, default='["en"]', nullable=False)
    poll_interval_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    historical_days: Mapped[int | None] = mapped_column(Integer)
    config_version: Mapped[str] = mapped_column(String(40), default="evidence-v1", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class EvidenceSourceState(Base):
    __tablename__ = "evidence_source_states"
    __table_args__ = (
        Index("ix_evidence_source_state_next_poll", "next_poll_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    source_config_id: Mapped[str] = mapped_column(
        ForeignKey("evidence_source_configs.id"), unique=True, nullable=False
    )
    cursor_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    etag: Mapped[str | None] = mapped_column(String(255))
    last_modified: Mapped[str | None] = mapped_column(String(255))
    next_poll_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_attempted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    healthy_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error_class: Mapped[str | None] = mapped_column(String(160))
    last_error_message: Mapped[str | None] = mapped_column(Text)
    diagnostics_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class DiscoveryCandidate(Base):
    __tablename__ = "discovery_candidates"
    __table_args__ = (
        UniqueConstraint(
            "source_config_id", "external_id", name="uq_discovery_candidate_external_id"
        ),
        UniqueConstraint("canonical_url_hash", name="uq_discovery_candidate_canonical_url_hash"),
        CheckConstraint(
            "status IN ("
            + ", ".join(f"'{status.value}'" for status in CandidateStatus)
            + ")",
            name="ck_discovery_candidate_status",
        ),
        CheckConstraint("retry_count >= 0", name="ck_discovery_candidate_retry_nonnegative"),
        Index("ix_discovery_candidate_status_attempt", "status", "next_attempt_at"),
        Index("ix_discovery_candidate_source_published", "source_config_id", "published_at"),
        Index("ix_discovery_candidate_topic_published", "topic", "published_at"),
        Index("ix_discovery_candidate_lease", "lease_expires_at"),
        Index("ix_discovery_candidate_event", "event_id"),
        Index("ix_discovery_candidate_artifact", "artifact_id"),
        Index("ix_discovery_candidate_body_hash", "body_sha256"),
        Index("ix_discovery_candidate_headline_hash", "normalized_headline_hash"),
        Index("ix_discovery_candidate_simhash", "simhash"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    source_config_id: Mapped[str] = mapped_column(
        ForeignKey("evidence_source_configs.id"), nullable=False
    )
    external_id: Mapped[str | None] = mapped_column(String(255))
    observed_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    canonical_url: Mapped[str | None] = mapped_column(String(1000))
    canonical_url_hash: Mapped[str | None] = mapped_column(String(64))
    headline: Mapped[str] = mapped_column(String(500), nullable=False)
    normalized_headline_hash: Mapped[str | None] = mapped_column(String(64))
    publisher: Mapped[str] = mapped_column(String(160), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    discovery_method: Mapped[str] = mapped_column(String(40), nullable=False)
    discovery_query: Mapped[str | None] = mapped_column(String(255))
    topic: Mapped[str | None] = mapped_column(String(120))
    language: Mapped[str | None] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(
        String(30), default=CandidateStatus.DISCOVERED.value, nullable=False
    )
    artifact_id: Mapped[str | None] = mapped_column(ForeignKey("source_artifacts.id"))
    event_id: Mapped[str | None] = mapped_column(ForeignKey("events.id"))
    body_sha256: Mapped[str | None] = mapped_column(String(64))
    simhash: Mapped[str | None] = mapped_column(String(16))
    relevance_score: Mapped[Decimal | None] = mapped_column(Numeric(8, 6))
    novelty_score: Mapped[Decimal | None] = mapped_column(Numeric(8, 6))
    quality_score: Mapped[Decimal | None] = mapped_column(Numeric(8, 6))
    scoring_reasons_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    configuration_version: Mapped[str] = mapped_column(
        String(40), default="evidence-v1", nullable=False
    )
    parser_version: Mapped[str | None] = mapped_column(String(80))
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_class: Mapped[str | None] = mapped_column(String(160))
    last_error_message: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class EvidenceRefreshRequest(Base):
    __tablename__ = "evidence_refresh_requests"
    __table_args__ = (
        CheckConstraint(
            "request_type IN ('targeted', 'historical')",
            name="ck_evidence_refresh_request_type",
        ),
        CheckConstraint(
            "status IN ('queued', 'running', 'processing', 'complete', 'partial', 'failed')",
            name="ck_evidence_refresh_status",
        ),
        CheckConstraint(
            "priority_class IN ('live', 'historical')",
            name="ck_evidence_refresh_priority",
        ),
        CheckConstraint("max_candidates > 0", name="ck_evidence_refresh_limit_positive"),
        CheckConstraint("fetch_budget > 0", name="ck_evidence_refresh_fetch_budget_positive"),
        CheckConstraint(
            "storage_budget_bytes > 0",
            name="ck_evidence_refresh_storage_budget_positive",
        ),
        Index("ix_evidence_refresh_status_priority", "status", "priority_class", "created_at"),
        Index("ix_evidence_refresh_user_created", "requested_by_user_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    requested_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), index=True)
    request_type: Mapped[str] = mapped_column(String(20), nullable=False)
    scope_key: Mapped[str] = mapped_column(String(160), nullable=False)
    query_text: Mapped[str | None] = mapped_column(String(500))
    source_keys_json: Mapped[str] = mapped_column(Text, default='["gdelt"]', nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="queued", nullable=False)
    priority_class: Mapped[str] = mapped_column(String(20), default="live", nullable=False)
    max_candidates: Mapped[int] = mapped_column(Integer, nullable=False)
    preset_key: Mapped[str | None] = mapped_column(String(40))
    date_from: Mapped[date | None] = mapped_column(Date)
    date_to: Mapped[date | None] = mapped_column(Date)
    progress_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    fetch_budget: Mapped[int] = mapped_column(Integer, default=50, nullable=False)
    storage_budget_bytes: Mapped[int] = mapped_column(
        BigInteger, default=250 * 1024 * 1024, nullable=False
    )
    fetched_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    fetched_bytes: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    discovered_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    selected_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    duplicate_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rejected_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_class: Mapped[str | None] = mapped_column(String(160))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )
