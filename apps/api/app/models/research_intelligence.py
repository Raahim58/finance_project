"""Owner-scoped saved research and durable, manually requested generation."""

from datetime import UTC, datetime
from uuid import uuid4
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column
from app.db.session import Base


def now():
    return datetime.now(UTC)


def uid():
    return str(uuid4())


class ResearchArtifact:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now, nullable=False
    )


class CompanyExposureProfile(ResearchArtifact, Base):
    __tablename__ = "company_exposure_profiles"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "instrument_id",
            "input_hash",
            "prompt_version",
            "provider",
            "model",
            name="uq_research_profile",
        ),
    )
    instrument_id: Mapped[str] = mapped_column(
        ForeignKey("instruments.id"), nullable=False, index=True
    )
    prompt_version: Mapped[str] = mapped_column(String(40), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    relationships_json: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_json: Mapped[str] = mapped_column(Text, nullable=False)
    coverage_json: Mapped[str] = mapped_column(Text, nullable=False)


class CompanyEventBrief(ResearchArtifact, Base):
    __tablename__ = "company_event_briefs"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "instrument_id",
            "event_key",
            "input_hash",
            "prompt_version",
            "provider",
            "model",
            name="uq_research_brief",
        ),
    )
    instrument_id: Mapped[str] = mapped_column(
        ForeignKey("instruments.id"), nullable=False, index=True
    )
    normalized_event_id: Mapped[str | None] = mapped_column(ForeignKey("normalized_events.id"))
    raw_event_id: Mapped[str | None] = mapped_column(ForeignKey("events.id"))
    event_key: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    prompt_version: Mapped[str] = mapped_column(String(40), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    brief_json: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_json: Mapped[str] = mapped_column(Text, nullable=False)


class PortfolioEventSnapshot(ResearchArtifact, Base):
    __tablename__ = "portfolio_event_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "portfolio_id", "input_hash", "calculation_version", name="uq_research_snapshot"
        ),
    )
    portfolio_id: Mapped[str] = mapped_column(
        ForeignKey("portfolios.id"), nullable=False, index=True
    )
    calculation_version: Mapped[str] = mapped_column(String(40), nullable=False)
    valuation_as_of: Mapped[str | None] = mapped_column(String(80))
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)


class ResearchJob(Base):
    __tablename__ = "research_jobs"
    __table_args__ = (
        UniqueConstraint("user_id", "dedup_key", name="uq_research_job_dedup"),
        Index("ix_research_job_claim", "status", "created_at"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("research_jobs.id"), index=True)
    portfolio_id: Mapped[str | None] = mapped_column(ForeignKey("portfolios.id"))
    instrument_id: Mapped[str | None] = mapped_column(ForeignKey("instruments.id"))
    job_type: Mapped[str] = mapped_column(String(30), nullable=False)
    dedup_key: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="queued", nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_encrypted: Mapped[str | None] = mapped_column(Text)
    result_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    max_calls: Mapped[int] = mapped_column(Integer, default=16, nullable=False)
    reserved_calls: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now, onupdate=now, nullable=False
    )


class ResearchAttempt(Base):
    __tablename__ = "research_attempts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    job_id: Mapped[str] = mapped_column(ForeignKey("research_jobs.id"), unique=True, nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_encrypted: Mapped[str | None] = mapped_column(Text)
    response_encrypted: Mapped[str | None] = mapped_column(Text)
    provider_request_id: Mapped[str | None] = mapped_column(String(255))
    usage_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    error_code: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now, nullable=False
    )


class CompanyDigest(ResearchArtifact, Base):
    """Company-only snapshot and interpretation; existing research jobs own generation."""
    __tablename__ = "company_digests"
    __table_args__ = (
        UniqueConstraint("user_id", "instrument_id", "input_hash", "prompt_version", "provider", "model", name="uq_company_digest"),
    )
    instrument_id: Mapped[str] = mapped_column(ForeignKey("instruments.id"), nullable=False, index=True)
    prompt_version: Mapped[str] = mapped_column(String(40), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)
    brief_json: Mapped[str | None] = mapped_column(Text)
