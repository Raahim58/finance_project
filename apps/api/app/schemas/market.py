from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


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
    shares_outstanding: Decimal | None = None
    free_float_shares: Decimal | None = None
    free_float_market_cap: Decimal | None = None
    capitalization_date: date | None = None
    capitalization_source_url: str | None = None
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
    source_url: str | None = None
    totals_note: str | None = None


class IndexCloseResponse(BaseModel):
    trade_date: date
    close: Decimal


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
    prices: list[MarketPriceResponse] = Field(default_factory=list)
    trade_date: date | None = None
    price_basis: Literal["daily", "intraday"] = "daily"
    priced_securities: int = 0
    observed_at: datetime | None = None
    latest_quote_date: date | None = None
    latest_quote_count: int = 0
    snapshot: MarketSnapshotResponse | None
    top_gainers: list[MarketPriceResponse]
    top_losers: list[MarketPriceResponse]
    top_volume: list[MarketPriceResponse]
    sectors: list[SectorDailyStatsResponse]


class MarketFreshnessResponse(BaseModel):
    price_basis: Literal["daily", "intraday"] = "daily"
    priced_securities: int = 0
    latest_quote_date: date | None = None
    latest_quote_count: int = 0
    source_freshness_sla_minutes: int | None = None
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
