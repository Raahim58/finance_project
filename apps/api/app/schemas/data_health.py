from datetime import datetime
from typing import Literal

from pydantic import BaseModel


HealthStatus = Literal["healthy", "stale", "partial", "failed", "never_run"]


class SourceHealthResponse(BaseModel):
    source: str
    status: HealthStatus
    last_attempt: datetime | None = None
    last_success: datetime | None = None
    latest_data_at: datetime | None = None
    attempted: int = 0
    accepted: int = 0
    updated: int = 0
    rejected: int = 0
    error: str | None = None
    freshness_sla_minutes: int | None = None


class DataHealthResponse(BaseModel):
    sources: list[SourceHealthResponse]


class CoverageCategory(BaseModel):
    available: bool
    count: int = 0
    latest_date: datetime | None = None
    reason: str | None = None


class PriceCoverage(CoverageCategory):
    observations: int = 0


class FundamentalCoverage(CoverageCategory):
    fact_count: int = 0
    latest_period: datetime | None = None


class CompanyCompletenessResponse(BaseModel):
    symbol: str
    price: PriceCoverage
    fundamentals: FundamentalCoverage
    reports: CoverageCategory
    announcements: CoverageCategory
    news: CoverageCategory
