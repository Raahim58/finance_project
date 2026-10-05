from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

Factor = Literal["oil_price", "pk_policy_rate", "usd_pkr"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BatchRequest(StrictModel):
    client_request_id: str = Field(min_length=1, max_length=100)
    portfolio_id: str | None = None
    instrument_ids: list[str] = Field(default_factory=list, max_length=8)
    max_companies: int = Field(default=8, ge=1, le=8)
    max_calls: int = Field(default=16, ge=0, le=16)

    @model_validator(mode="after")
    def scope(self):
        if bool(self.portfolio_id) == bool(self.instrument_ids):
            raise ValueError("Select a portfolio or company IDs, exclusively")
        if len(set(self.instrument_ids)) != len(self.instrument_ids):
            raise ValueError("Company IDs must be distinct")
        return self


class SupportingQuote(StrictModel):
    evidence_id: str
    quote: str = Field(min_length=1, max_length=500)


class ExposureRelationship(StrictModel):
    factor: Factor
    channel: Literal[
        "revenue", "operating_cost", "financing", "balance_sheet", "translation", "other"
    ]
    mechanism: str = Field(min_length=1, max_length=240)
    conditions: list[str] = Field(default_factory=list, max_length=3)
    evidence_ids: list[str] = Field(min_length=1, max_length=12)
    supporting_quotes: list[SupportingQuote] = Field(min_length=1, max_length=6)
    status: Literal["ai_proposed"]


class ProfileOutput(StrictModel):
    relationships: list[ExposureRelationship] = Field(max_length=6)
    coverage_gaps: list[str] = Field(max_length=6)


class Claim(StrictModel):
    text: str = Field(min_length=1, max_length=800)
    evidence_ids: list[str] = Field(default_factory=list, max_length=12)
    fact_ids: list[str] = Field(default_factory=list, max_length=12)


class EventExplanation(StrictModel):
    event_key: str
    relationship_kind: Literal["direct", "ai_proposed_indirect"]
    status: Literal["explained", "insufficient_evidence"]
    what_happened: Claim
    why_it_matters: list[Claim] = Field(max_length=3)
    countereffects: list[Claim] = Field(max_length=2)
    unknowns: list[str] = Field(max_length=3)


class DigestOutput(StrictModel):
    events: list[EventExplanation] = Field(max_length=5)


class DigestClaim(StrictModel):
    text: str = Field(min_length=1, max_length=600)
    kind: Literal['interpretation', 'reported', 'management_claim']
    refs: list[str] = Field(min_length=1, max_length=8)


class CompanyBriefOutput(StrictModel):
    thesis: list[DigestClaim] = Field(max_length=3)
    earnings_drivers: list[DigestClaim] = Field(max_length=3)
    valuation: list[DigestClaim] = Field(max_length=2)
    catalysts: list[DigestClaim] = Field(max_length=3)
    risks: list[DigestClaim] = Field(max_length=3)
    unresolved_questions: list[str] = Field(max_length=6)
