import json
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


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
    preset: Literal["psx_12m", "deep_company_12m", "news_90d"] = "deep_company_12m"
    symbol: str | None = Field(default=None, min_length=1, max_length=30)
    date_from: date | None = None
    date_to: date | None = None
    source_keys: list[Literal["psx_announcements", "gdelt"]] | None = Field(
        default=None, min_length=1
    )
    max_candidates: int | None = Field(default=None, ge=1, le=10000)
    fetch_budget: int | None = Field(default=None, ge=1, le=5000)
    storage_budget_mb: int | None = Field(default=None, ge=1, le=10240)

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str | None) -> str | None:
        return value.strip().upper() if value else None

    @model_validator(mode="after")
    def validate_scope(self) -> "EvidenceHistoricalCreate":
        if self.preset == "deep_company_12m" and not self.symbol:
            raise ValueError("symbol is required for deep_company_12m")
        if self.date_from and self.date_to:
            if self.date_from > self.date_to:
                raise ValueError("date_from must not be after date_to")
            if (self.date_to - self.date_from).days > 365:
                raise ValueError("Pass 3 historical hydration is capped at 12 months")
        return self


class EvidenceRefreshResponse(BaseModel):
    id: str
    request_type: str
    scope_key: str
    status: str
    priority_class: str
    max_candidates: int
    preset_key: str | None
    date_from: date | None
    date_to: date | None
    progress: dict = Field(validation_alias="progress_json")
    fetch_budget: int
    storage_budget_bytes: int
    fetched_count: int
    fetched_bytes: int
    discovered_count: int
    selected_count: int
    duplicate_count: int
    rejected_count: int
    error_class: str | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None

    @field_validator("progress", mode="before")
    @classmethod
    def parse_progress(cls, value: str | dict) -> dict:
        return json.loads(value) if isinstance(value, str) else value
