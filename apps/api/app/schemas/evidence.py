from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class EvidenceRefreshCreate(BaseModel):
    scope_type: Literal["symbol", "topic", "sector", "query"]
    value: str = Field(min_length=2, max_length=300)
    max_candidates: int = Field(default=25, ge=1, le=100)

    @field_validator("value")
    @classmethod
    def clean_value(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if not cleaned:
            raise ValueError("Refresh value cannot be blank")
        return cleaned


class EvidenceHistoricalCreate(BaseModel):
    symbol: str = Field(min_length=1, max_length=30)
    max_candidates: int = Field(default=50, ge=1, le=100)

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        return value.strip().upper()


class EvidenceRefreshResponse(BaseModel):
    id: str
    request_type: str
    scope_key: str
    status: str
    priority_class: str
    max_candidates: int
    discovered_count: int
    selected_count: int
    duplicate_count: int
    rejected_count: int
    error_class: str | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
