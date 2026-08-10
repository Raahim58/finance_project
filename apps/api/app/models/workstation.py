from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


def uuid_str() -> str:
    return str(uuid4())


def utcnow() -> datetime:
    return datetime.now(UTC)


class Instrument(Base):
    __tablename__ = "instruments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    company_id: Mapped[str | None] = mapped_column(ForeignKey("companies.id"), unique=True, index=True)
    symbol: Mapped[str] = mapped_column(String(30), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    instrument_type: Mapped[str] = mapped_column(String(40), default="equity", nullable=False)
    currency: Mapped[str] = mapped_column(String(10), default="PKR", nullable=False)
    country: Mapped[str] = mapped_column(String(2), default="PK", nullable=False)
    sector: Mapped[str | None] = mapped_column(String(120), index=True)
    active_from: Mapped[date | None] = mapped_column(Date)
    active_to: Mapped[date | None] = mapped_column(Date)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)


class DataSource(Base):
    __tablename__ = "data_sources"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    source_type: Mapped[str] = mapped_column(String(40), nullable=False)
    base_url: Mapped[str | None] = mapped_column(String(500))
    priority: Mapped[int] = mapped_column(default=100, nullable=False)
    freshness_sla_minutes: Mapped[int | None] = mapped_column()
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    use_notes: Mapped[str | None] = mapped_column(Text)


class SourceArtifact(Base):
    __tablename__ = "source_artifacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    data_source_id: Mapped[str] = mapped_column(ForeignKey("data_sources.id"), index=True)
    source_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    effective_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sha256: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    content_type: Mapped[str | None] = mapped_column(String(120))
    storage_path: Mapped[str | None] = mapped_column(String(1000))
    parser_version: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="captured", nullable=False)
    response_metadata_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)


class InvestorFinancialProfileVersion(Base):
    __tablename__ = "investor_financial_profile_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    version: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)
    profile_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class PortfolioIPSVersion(Base):
    __tablename__ = "portfolio_ips_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    portfolio_id: Mapped[str] = mapped_column(ForeignKey("portfolios.id"), index=True, nullable=False)
    version: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)
    constraints_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    required_return: Mapped[Decimal | None] = mapped_column(Numeric(12, 8))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class AllocationSet(Base):
    __tablename__ = "allocation_sets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    portfolio_id: Mapped[str] = mapped_column(ForeignKey("portfolios.id"), index=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    version: Mapped[int] = mapped_column(default=1, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)
    assumptions_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class AllocationItem(Base):
    __tablename__ = "allocation_items"
    __table_args__ = (UniqueConstraint("allocation_set_id", "symbol", name="uq_allocation_symbol"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    allocation_set_id: Mapped[str] = mapped_column(ForeignKey("allocation_sets.id"), index=True)
    symbol: Mapped[str] = mapped_column(String(30), nullable=False)
    target_weight: Mapped[Decimal] = mapped_column(Numeric(12, 8), nullable=False)
    locked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class OptimizerRun(Base):
    __tablename__ = "optimizer_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    portfolio_id: Mapped[str] = mapped_column(ForeignKey("portfolios.id"), index=True, nullable=False)
    objective: Mapped[str] = mapped_column(String(40), nullable=False)
    expected_return_method: Mapped[str | None] = mapped_column(String(40))
    data_cutoff: Mapped[date] = mapped_column(Date, nullable=False)
    input_json: Mapped[str] = mapped_column(Text, nullable=False)
    result_json: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    diagnostics_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class ScenarioRun(Base):
    __tablename__ = "scenario_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    portfolio_id: Mapped[str] = mapped_column(ForeignKey("portfolios.id"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    shocks_json: Mapped[str] = mapped_column(Text, nullable=False)
    result_json: Mapped[str] = mapped_column(Text, nullable=False)
    data_cutoff: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class Recommendation(Base):
    __tablename__ = "recommendations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    portfolio_id: Mapped[str] = mapped_column(ForeignKey("portfolios.id"), index=True, nullable=False)
    trigger: Mapped[str] = mapped_column(String(80), nullable=False)
    evidence_json: Mapped[str] = mapped_column(Text, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="open", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class MonitoringRule(Base):
    __tablename__ = "monitoring_rules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    portfolio_id: Mapped[str] = mapped_column(ForeignKey("portfolios.id"), index=True, nullable=False)
    rule_type: Mapped[str] = mapped_column(String(60), nullable=False)
    threshold_json: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
