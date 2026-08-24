from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel


class EventSubjectResponse(BaseModel):
    subject_type: Literal["instrument", "sector", "macro_factor", "geography"]
    subject_key: str
    link_method: str
    confidence: Decimal
    is_direct: bool


class EventEvidenceResponse(BaseModel):
    raw_event_id: str
    source_name: str
    source_url: str
    published_at: datetime | None
    document_id: str | None


class NormalizedEventResponse(BaseModel):
    id: str
    event_type: str
    classification_status: Literal["classified", "unclassified"]
    title: str
    occurred_at: datetime
    event_time_end: datetime | None
    factor: str | None
    geography: str | None
    magnitude: Decimal | None
    magnitude_unit: str | None
    materiality: Literal["low", "medium", "high", "unknown"]
    confidence: Decimal
    freshness_score: Decimal
    freshness_status: Literal["fresh", "recent", "stale"]
    detection_version: str
    details: dict[str, object]
    subjects: list[EventSubjectResponse]
    evidence: list[EventEvidenceResponse]
    impact: dict[str, object]


class HoldingEventExposure(BaseModel):
    symbol: str
    current_portfolio_weight: float


class PortfolioEventItem(BaseModel):
    event: NormalizedEventResponse
    holdings: list[HoldingEventExposure]
    affected_portfolio_weight: float
    impact_direction: None = None
    impact_calculation: str


class PortfolioEventsResponse(BaseModel):
    portfolio_id: str
    events: list[PortfolioEventItem]
    impact_calculation: str
