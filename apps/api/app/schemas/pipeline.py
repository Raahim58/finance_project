"""Strict, quote-grounded extraction contract; model numbers are never SQL facts."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

StatementKind = Literal['reported_fact','secondary_report','management_claim','guidance','commentary','background','rumor','interpretation']
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


# Article classification: one record per distinct event an article reports.
# Every field that is not supported by a verbatim quote is stored as unknown.
EventDirection = Literal['increase','decrease','new','unchanged','unknown']
Topic = Literal['earnings','dividends','capacity','financing','regulation','governance','ownership',
    'pricing','demand','costs','energy','commodities','inflation','rates','fx','fiscal','trade','geopolitics','other']

class EvidenceSpan(BaseModel):
    model_config = ConfigDict(extra='forbid')
    section_id: str
    quote: str = Field(min_length=1, max_length=600)

class AmountClaim(BaseModel):
    model_config = ConfigDict(extra='forbid')
    value: str = Field(max_length=40)
    unit: str = Field(max_length=30)
    quote: str = Field(min_length=1, max_length=600)

class SourcedValue(BaseModel):
    model_config = ConfigDict(extra='forbid')
    value: str = Field(max_length=40)
    quote: str = Field(min_length=1, max_length=600)

class ClassifiedEvent(BaseModel):
    model_config = ConfigDict(extra='forbid')
    entities: list[str] = Field(max_length=8)
    event_type: EventType
    kind: StatementKind
    lifecycle: Lifecycle
    direction: EventDirection
    event_date: SourcedValue | None
    reporting_period: SourcedValue | None
    counterparties: list[str] = Field(max_length=6)
    amounts: list[AmountClaim] = Field(max_length=6)
    topics: list[Topic] = Field(max_length=6)
    sentiment: Sentiment | None
    evidence: list[EvidenceSpan] = Field(min_length=1, max_length=3)

class ArticleClassification(BaseModel):
    model_config = ConfigDict(extra='forbid')
    events: list[ClassifiedEvent] = Field(max_length=12)
