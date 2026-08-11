from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
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


class InstrumentAlias(Base):
    __tablename__ = "instrument_aliases"
    __table_args__ = (UniqueConstraint("provider", "alias", "valid_from", name="uq_instrument_alias_validity"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    instrument_id: Mapped[str] = mapped_column(ForeignKey("instruments.id"), index=True, nullable=False)
    provider: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    alias: Mapped[str] = mapped_column(String(120), index=True, nullable=False)
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)


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
    http_method: Mapped[str] = mapped_column(String(10), default="GET", nullable=False)
    request_fingerprint: Mapped[str | None] = mapped_column(String(64), index=True)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    source_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    effective_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sha256: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    content_type: Mapped[str | None] = mapped_column(String(120))
    storage_path: Mapped[str | None] = mapped_column(String(1000))
    parser_version: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="captured", nullable=False)
    response_metadata_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"
    __table_args__ = (UniqueConstraint("job_key", "run_key", name="uq_ingestion_job_run"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    job_key: Mapped[str] = mapped_column(String(120), index=True, nullable=False)
    run_key: Mapped[str] = mapped_column(String(160), nullable=False)
    provider: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(30), index=True, nullable=False)
    parent_run_id: Mapped[str | None] = mapped_column(ForeignKey("ingestion_runs.id"))
    attempted_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    accepted_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rejected_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_class: Mapped[str | None] = mapped_column(String(160))
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DataQualityIssue(Base):
    __tablename__ = "data_quality_issues"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    artifact_id: Mapped[str | None] = mapped_column(ForeignKey("source_artifacts.id"), index=True)
    observation_id: Mapped[str | None] = mapped_column(String(36), index=True)
    rule: Mapped[str] = mapped_column(String(120), index=True, nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    details_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    resolution: Mapped[str | None] = mapped_column(Text)
    selection_status: Mapped[str] = mapped_column(String(20), default="rejected", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class MarketObservation(Base):
    __tablename__ = "market_observations"
    __table_args__ = (UniqueConstraint("instrument_id", "effective_at", "frequency", "artifact_id", name="uq_market_observation_source"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    instrument_id: Mapped[str | None] = mapped_column(ForeignKey("instruments.id"), index=True)
    series_key: Mapped[str | None] = mapped_column(String(160), index=True)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
    frequency: Mapped[str] = mapped_column(String(20), nullable=False)
    values_json: Mapped[str] = mapped_column(Text, nullable=False)
    currency: Mapped[str | None] = mapped_column(String(10))
    unit: Mapped[str | None] = mapped_column(String(40))
    adjustment_state: Mapped[str] = mapped_column(String(40), default="unadjusted", nullable=False)
    artifact_id: Mapped[str] = mapped_column(ForeignKey("source_artifacts.id"), index=True, nullable=False)
    is_selected: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)


class ExchangeCalendarDay(Base):
    __tablename__ = "exchange_calendar_days"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    exchange_code: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    session_date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    is_session: Mapped[bool] = mapped_column(Boolean, nullable=False)
    open_time: Mapped[str | None] = mapped_column(String(10))
    close_time: Mapped[str | None] = mapped_column(String(10))
    reason: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), default="observed", nullable=False)
    artifact_id: Mapped[str | None] = mapped_column(ForeignKey("source_artifacts.id"), index=True)


class InvestorFinancialProfile(Base):
    __tablename__ = "investor_financial_profiles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), unique=True, index=True, nullable=False)
    current_version_id: Mapped[str | None] = mapped_column(String(36))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class InvestorFinancialProfileVersion(Base):
    __tablename__ = "investor_financial_profile_versions"
    __table_args__ = (UniqueConstraint("user_id", "version", name="uq_profile_version"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    version: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)
    profile_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class PortfolioIPSVersion(Base):
    __tablename__ = "portfolio_ips_versions"
    __table_args__ = (UniqueConstraint("portfolio_id", "version", name="uq_ips_version"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    portfolio_id: Mapped[str] = mapped_column(ForeignKey("portfolios.id"), index=True, nullable=False)
    version: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)
    constraints_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    required_return: Mapped[Decimal | None] = mapped_column(Numeric(12, 8))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class PortfolioIPS(Base):
    __tablename__ = "portfolio_ips"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    portfolio_id: Mapped[str] = mapped_column(ForeignKey("portfolios.id"), unique=True, index=True, nullable=False)
    current_version_id: Mapped[str | None] = mapped_column(ForeignKey("portfolio_ips_versions.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class PortfolioCashAccount(Base):
    __tablename__ = "portfolio_cash_accounts"
    __table_args__ = (UniqueConstraint("portfolio_id", "currency", "name", name="uq_portfolio_cash_account"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    portfolio_id: Mapped[str] = mapped_column(ForeignKey("portfolios.id"), index=True, nullable=False)
    currency: Mapped[str] = mapped_column(String(10), nullable=False)
    name: Mapped[str] = mapped_column(String(120), default="Primary", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class PortfolioPositionSnapshot(Base):
    __tablename__ = "portfolio_position_snapshots"
    __table_args__ = (UniqueConstraint("portfolio_id", "instrument_id", "snapshot_date", name="uq_position_snapshot"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    portfolio_id: Mapped[str] = mapped_column(ForeignKey("portfolios.id"), index=True, nullable=False)
    instrument_id: Mapped[str] = mapped_column(ForeignKey("instruments.id"), index=True, nullable=False)
    snapshot_date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)
    average_cost: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    source_transaction_id: Mapped[str | None] = mapped_column(ForeignKey("portfolio_transactions.id"))


class PortfolioCashSnapshot(Base):
    __tablename__ = "portfolio_cash_snapshots"
    __table_args__ = (UniqueConstraint("cash_account_id", "snapshot_date", name="uq_cash_snapshot"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    cash_account_id: Mapped[str] = mapped_column(ForeignKey("portfolio_cash_accounts.id"), index=True, nullable=False)
    snapshot_date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    balance: Mapped[Decimal] = mapped_column(Numeric(24, 4), nullable=False)
    source_transaction_id: Mapped[str | None] = mapped_column(ForeignKey("portfolio_transactions.id"))


class AllocationSet(Base):
    __tablename__ = "allocation_sets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    portfolio_id: Mapped[str] = mapped_column(ForeignKey("portfolios.id"), index=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    version: Mapped[int] = mapped_column(default=1, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)
    assumptions_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    base_value: Mapped[Decimal | None] = mapped_column(Numeric(24, 4))
    created_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class AllocationItem(Base):
    __tablename__ = "allocation_items"
    __table_args__ = (UniqueConstraint("allocation_set_id", "symbol", name="uq_allocation_symbol"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    allocation_set_id: Mapped[str] = mapped_column(ForeignKey("allocation_sets.id"), index=True)
    symbol: Mapped[str] = mapped_column(String(30), nullable=False)
    instrument_id: Mapped[str | None] = mapped_column(ForeignKey("instruments.id"), index=True)
    is_cash: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    target_weight: Mapped[Decimal] = mapped_column(Numeric(12, 8), nullable=False)
    target_amount: Mapped[Decimal | None] = mapped_column(Numeric(24, 4))
    target_quantity: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    locked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class OptimizerRun(Base):
    __tablename__ = "optimizer_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    portfolio_id: Mapped[str] = mapped_column(ForeignKey("portfolios.id"), index=True, nullable=False)
    objective: Mapped[str] = mapped_column(String(40), nullable=False)
    expected_return_method: Mapped[str | None] = mapped_column(String(40))
    ips_version_id: Mapped[str | None] = mapped_column(ForeignKey("portfolio_ips_versions.id"), index=True)
    data_cutoff: Mapped[date] = mapped_column(Date, nullable=False)
    bounds_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    solver: Mapped[str | None] = mapped_column(String(60))
    seed: Mapped[int | None] = mapped_column(Integer)
    input_json: Mapped[str] = mapped_column(Text, nullable=False)
    result_json: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    diagnostics_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    portfolio_id: Mapped[str | None] = mapped_column(ForeignKey("portfolios.id"), index=True)
    instrument_id: Mapped[str | None] = mapped_column(ForeignKey("instruments.id"), index=True)
    analysis_type: Mapped[str] = mapped_column(String(60), index=True, nullable=False)
    input_fingerprint: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    data_cutoff: Mapped[date] = mapped_column(Date, nullable=False)
    estimator_json: Mapped[str] = mapped_column(Text, nullable=False)
    code_version: Mapped[str] = mapped_column(String(80), nullable=False)
    result_json: Mapped[str] = mapped_column(Text, nullable=False)
    artifact_hashes_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class OptimizerAllocation(Base):
    __tablename__ = "optimizer_allocations"
    __table_args__ = (UniqueConstraint("optimizer_run_id", "instrument_id", name="uq_optimizer_instrument"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    optimizer_run_id: Mapped[str] = mapped_column(ForeignKey("optimizer_runs.id"), index=True, nullable=False)
    instrument_id: Mapped[str] = mapped_column(ForeignKey("instruments.id"), index=True, nullable=False)
    weight: Mapped[Decimal] = mapped_column(Numeric(12, 8), nullable=False)


class ScenarioRun(Base):
    __tablename__ = "scenario_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    portfolio_id: Mapped[str] = mapped_column(ForeignKey("portfolios.id"), index=True, nullable=False)
    scenario_definition_id: Mapped[str | None] = mapped_column(ForeignKey("scenario_definitions.id"), index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    shocks_json: Mapped[str] = mapped_column(Text, nullable=False)
    result_json: Mapped[str] = mapped_column(Text, nullable=False)
    data_cutoff: Mapped[date] = mapped_column(Date, nullable=False)
    assumptions_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="completed", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class ScenarioDefinition(Base):
    __tablename__ = "scenario_definitions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    portfolio_id: Mapped[str | None] = mapped_column(ForeignKey("portfolios.id"), index=True)
    owner_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    scenario_type: Mapped[str] = mapped_column(String(30), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    assumptions_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class ScenarioShock(Base):
    __tablename__ = "scenario_shocks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    scenario_definition_id: Mapped[str] = mapped_column(ForeignKey("scenario_definitions.id"), index=True, nullable=False)
    target_type: Mapped[str] = mapped_column(String(30), nullable=False)
    target_key: Mapped[str] = mapped_column(String(160), nullable=False)
    shock_value: Mapped[Decimal] = mapped_column(Numeric(14, 8), nullable=False)
    unit: Mapped[str] = mapped_column(String(30), default="return", nullable=False)


class Recommendation(Base):
    __tablename__ = "recommendations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    portfolio_id: Mapped[str] = mapped_column(ForeignKey("portfolios.id"), index=True, nullable=False)
    trigger: Mapped[str] = mapped_column(String(160), nullable=False)
    evidence_json: Mapped[str] = mapped_column(Text, nullable=False)
    ips_violation_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    assumptions_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    expected_effect_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    uncertainty_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    freshness_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
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
    deduplication_window_minutes: Mapped[int] = mapped_column(Integer, default=1440, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class MacroSeries(Base):
    __tablename__ = "macro_series"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    key: Mapped[str] = mapped_column(String(160), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    unit: Mapped[str] = mapped_column(String(60), nullable=False)
    frequency: Mapped[str] = mapped_column(String(30), nullable=False)
    source_id: Mapped[str] = mapped_column(ForeignKey("data_sources.id"), index=True, nullable=False)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)


class MacroObservation(Base):
    __tablename__ = "macro_observations"
    __table_args__ = (UniqueConstraint("series_id", "effective_date", "release_at", name="uq_macro_revision"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    series_id: Mapped[str] = mapped_column(ForeignKey("macro_series.id"), index=True, nullable=False)
    effective_date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    release_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    value: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    artifact_id: Mapped[str | None] = mapped_column(ForeignKey("source_artifacts.id"))
    is_selected: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class FinancialFact(Base):
    __tablename__ = "financial_facts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    instrument_id: Mapped[str] = mapped_column(ForeignKey("instruments.id"), index=True, nullable=False)
    taxonomy_key: Mapped[str] = mapped_column(String(160), index=True, nullable=False)
    period_type: Mapped[str] = mapped_column(String(30), nullable=False)
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    filing_date: Mapped[date | None] = mapped_column(Date)
    value: Mapped[Decimal] = mapped_column(Numeric(30, 8), nullable=False)
    unit: Mapped[str] = mapped_column(String(40), nullable=False)
    currency: Mapped[str | None] = mapped_column(String(10))
    consolidated: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    document_id: Mapped[str | None] = mapped_column(ForeignKey("documents.id"), index=True)
    page_number: Mapped[int | None] = mapped_column(Integer)


class CorporateAction(Base):
    __tablename__ = "corporate_actions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    instrument_id: Mapped[str] = mapped_column(ForeignKey("instruments.id"), index=True, nullable=False)
    action_type: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    effective_date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    ex_date: Mapped[date | None] = mapped_column(Date)
    payment_date: Mapped[date | None] = mapped_column(Date)
    details_json: Mapped[str] = mapped_column(Text, nullable=False)
    artifact_id: Mapped[str | None] = mapped_column(ForeignKey("source_artifacts.id"))


class Event(Base):
    __tablename__ = "events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    event_type: Mapped[str] = mapped_column(String(60), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
    materiality: Mapped[str | None] = mapped_column(String(20))
    direction: Mapped[str | None] = mapped_column(String(20))
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(8, 6))
    details_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)


class EventSource(Base):
    __tablename__ = "event_sources"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id"), index=True, nullable=False)
    source_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    source_name: Mapped[str] = mapped_column(String(120), nullable=False)
    artifact_id: Mapped[str | None] = mapped_column(ForeignKey("source_artifacts.id"))
    document_id: Mapped[str | None] = mapped_column(ForeignKey("documents.id"))


class EventEntityLink(Base):
    __tablename__ = "event_entity_links"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id"), index=True, nullable=False)
    entity_type: Mapped[str] = mapped_column(String(30), nullable=False)
    entity_key: Mapped[str] = mapped_column(String(160), index=True, nullable=False)
    link_method: Mapped[str] = mapped_column(String(30), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False)


class Conversation(Base):
    __tablename__ = "assistant_conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    portfolio_id: Mapped[str | None] = mapped_column(ForeignKey("portfolios.id"), index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class AssistantMessage(Base):
    __tablename__ = "assistant_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("assistant_conversations.id"), index=True, nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    tool_trace_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class MonitoringRun(Base):
    __tablename__ = "monitoring_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    portfolio_id: Mapped[str] = mapped_column(ForeignKey("portfolios.id"), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    evidence_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    portfolio_id: Mapped[str] = mapped_column(ForeignKey("portfolios.id"), index=True, nullable=False)
    monitoring_run_id: Mapped[str | None] = mapped_column(ForeignKey("monitoring_runs.id"))
    deduplication_key: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    alert_type: Mapped[str] = mapped_column(String(60), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="open", nullable=False)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
