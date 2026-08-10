from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class InstrumentResponse(BaseModel):
    id: str
    symbol: str
    name: str
    instrument_type: str
    currency: str
    country: str
    sector: str | None
    active_from: date | None
    active_to: date | None
    metadata: dict[str, object]


class ScenarioShockInput(BaseModel):
    target_type: str = Field(pattern="^(instrument|sector|factor|index|fx|rate|inflation|commodity)$")
    target_key: str = Field(min_length=1, max_length=160)
    shock_value: Decimal
    unit: str = Field(default="return", max_length=30)


class ScenarioDefinitionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    scenario_type: str = Field(default="user", pattern="^(user|historical|ai_proposed)$")
    description: str | None = None
    assumptions: dict[str, object] = Field(default_factory=dict)
    shocks: list[ScenarioShockInput] = Field(min_length=1)


class ScenarioDefinitionResponse(BaseModel):
    id: str
    portfolio_id: str | None
    name: str
    scenario_type: str
    description: str | None
    assumptions: dict[str, object]
    shocks: list[dict[str, object]]
    created_at: datetime


class HistoricalReplayRequest(BaseModel):
    start_date: date
    end_date: date
    use_current_holdings: bool = False

