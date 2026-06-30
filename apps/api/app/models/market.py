from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


def uuid_str() -> str:
    return str(uuid4())


class Exchange(Base):
    __tablename__ = "exchanges"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    timezone: Mapped[str] = mapped_column(String(80), default="Asia/Karachi", nullable=False)

    companies: Mapped[list["Company"]] = relationship(back_populates="exchange")


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    symbol: Mapped[str] = mapped_column(String(30), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    sector: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    exchange_id: Mapped[str] = mapped_column(ForeignKey("exchanges.id"), nullable=False)
    official_website: Mapped[str | None] = mapped_column(String(500), nullable=True)
    psx_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    exchange: Mapped[Exchange] = relationship(back_populates="companies")
    prices: Mapped[list["MarketPrice"]] = relationship(
        back_populates="company", cascade="all, delete-orphan"
    )


class MarketPrice(Base):
    __tablename__ = "market_prices"
    __table_args__ = (
        UniqueConstraint("symbol", "trade_date", "source", name="uq_market_prices_symbol_date_source"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    open: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    high: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    low: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    close: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    previous_close: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    change: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    change_percent: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    volume: Mapped[int] = mapped_column(nullable=False)
    value: Mapped[Decimal] = mapped_column(Numeric(24, 4), nullable=False)
    market_cap: Mapped[Decimal | None] = mapped_column(Numeric(24, 4), nullable=True)
    source: Mapped[str] = mapped_column(String(80), default="mock", nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    company: Mapped[Company] = relationship(back_populates="prices")


class MarketSnapshot(Base):
    __tablename__ = "market_snapshots"
    __table_args__ = (
        UniqueConstraint("snapshot_date", "index_name", "source", name="uq_market_snapshot_date_index"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    index_name: Mapped[str] = mapped_column(String(120), nullable=False)
    index_value: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    index_change: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    index_change_percent: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    total_volume: Mapped[int] = mapped_column(nullable=False)
    total_value: Mapped[Decimal] = mapped_column(Numeric(24, 4), nullable=False)
    source: Mapped[str] = mapped_column(String(80), default="mock", nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )


class SectorDailyStats(Base):
    __tablename__ = "sector_daily_stats"
    __table_args__ = (
        UniqueConstraint("sector", "trade_date", "source", name="uq_sector_stats_sector_date_source"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    sector: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    total_volume: Mapped[int] = mapped_column(nullable=False)
    total_value: Mapped[Decimal] = mapped_column(Numeric(24, 4), nullable=False)
    average_change_percent: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    advancers: Mapped[int] = mapped_column(default=0, nullable=False)
    decliners: Mapped[int] = mapped_column(default=0, nullable=False)
    unchanged: Mapped[int] = mapped_column(default=0, nullable=False)
    source: Mapped[str] = mapped_column(String(80), default="mock", nullable=False)


class MarketIngestionRun(Base):
    __tablename__ = "market_ingestion_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    mode: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    latest_trade_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    records_written: Mapped[int] = mapped_column(default=0, nullable=False)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
