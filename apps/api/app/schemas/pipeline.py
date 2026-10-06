"""Strict, quote-grounded extraction contract; model numbers are never SQL facts."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

StatementKind = Literal['reported_fact','management_claim','guidance','commentary','background','rumor','interpretation']
Lifecycle = Literal['proposed','announced','approved','effective','completed','cancelled','updated','unknown']
EventType = Literal['earnings','guidance','dividend','corporate_action','financing','expansion','disruption','regulatory','governance','ownership','macro','geopolitics']

class Sentiment(BaseModel):
    model_config = ConfigDict(extra='forbid')
    subject_key: str
    aspect: Literal['issuer_outlook','earnings_quality','demand','pricing','costs','margins','liquidity','financing','regulation','sector_macro']
    direction: Literal['positive','negative','mixed','neutral','unknown']
    horizon: Literal['historical','current','forward','unknown']
    quote: str

class StatementCandidate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    section_id: str
    subject_key: str
    quote: str = Field(min_length=1, max_length=6000)
    kind: StatementKind
    event_type: EventType | None
    lifecycle: Lifecycle
    topics: list[str] = Field(max_length=12)
    attribution: str | None
    sentiment: Sentiment | None

class StatementBatch(BaseModel):
    model_config = ConfigDict(extra='forbid')
    statements: list[StatementCandidate] = Field(max_length=20)
