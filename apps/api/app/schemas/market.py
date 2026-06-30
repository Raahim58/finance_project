from datetime import date, datetime
from decimal import Decimal

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
    ingested_at: datetime


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
