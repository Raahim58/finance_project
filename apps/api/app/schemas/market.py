from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel


class ExchangeResponse(BaseModel):
    code: str
    name: str
    timezone: str


class CompanyResponse(BaseModel):
    id: str
    symbol: str
    name: str
    sector: str
    exchange: ExchangeResponse
    official_website: str | None = None
    psx_url: str | None = None
    description: str | None = None
    is_active: bool


class MarketPriceResponse(BaseModel):
    symbol: str
    trade_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    previous_close: Decimal
    change: Decimal
    change_percent: Decimal
    volume: int
    value: Decimal
    market_cap: Decimal | None = None
    source: str
    source_url: str | None = None
    ingested_at: datetime | None


class MarketSnapshotResponse(BaseModel):
    snapshot_date: date
    index_name: str
    index_value: Decimal
    index_change: Decimal
    index_change_percent: Decimal
    total_volume: int
    total_value: Decimal
    source: str
    ingested_at: datetime


class SectorDailyStatsResponse(BaseModel):
    sector: str
    trade_date: date
    total_volume: int
    total_value: Decimal
    average_change_percent: Decimal
    advancers: int
    decliners: int
    unchanged: int
    source: str


class CompanyDetailResponse(BaseModel):
    company: CompanyResponse
    latest_price: MarketPriceResponse | None = None


class MarketOverviewResponse(BaseModel):
    snapshot: MarketSnapshotResponse | None
    top_gainers: list[MarketPriceResponse]
    top_losers: list[MarketPriceResponse]
    top_volume: list[MarketPriceResponse]
    sectors: list[SectorDailyStatsResponse]


class MarketFreshnessResponse(BaseModel):
    market_data_mode: str
    refresh_seconds: int
    last_successful_ingestion_at: datetime | None
    latest_trade_date: date | None
    latest_source: str | None
    latest_attempted_provider: str | None = None
    latest_used_provider: str | None = None
    is_stale: bool
    stale_warning: str | None
    backup_warning: str | None = None
    # Split fields: "stale" previously conflated mock-mode, ingestion age, and
    # trade-date/session status into one boolean and one warning string.
    ingestion_age_seconds: float | None = None
    provider_mode_warning: str | None = None
    ingestion_staleness_warning: str | None = None
    fallback_provider_active: bool = False
    trade_date_status: Literal["current", "prior_session", "stale", "unknown"] = "unknown"
    exchange_session_status: Literal["open", "closed", "unknown"] = "unknown"
    exchange_session_note: str | None = None
