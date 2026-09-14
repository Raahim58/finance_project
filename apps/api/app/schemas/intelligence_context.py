"""Versioned contracts for deterministic intelligence context assembly."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


CONTEXT_CONTRACT_VERSION = "7a.v1"


class ContextScope(StrEnum):
    COMPANY_INTELLIGENCE = "company_intelligence"
    PORTFOLIO_RELEVANCE = "portfolio_relevance"
    SECURITY_FIT = "security_fit"


class ContextSectionName(StrEnum):
    PORTFOLIO = "portfolio"
    IPS = "ips"
    COMPANY_FACTS = "company_facts"
    MARKET_RISK = "market_risk"
    SECTOR = "sector"
    MACRO = "macro"
    EVENTS = "events"
    RAG_EVIDENCE = "rag_evidence"


class ContextState(StrEnum):
    CURRENT = "current"
    STALE = "stale"
    INCOMPLETE = "incomplete"
    MISSING = "missing"
    NOT_EVALUATED = "not_evaluated"
    REFRESHING = "refreshing"
    NOT_REQUESTED = "not_requested"


class ResearchPurpose(StrEnum):
    RECENT_CHANGES = "recent_changes"
    OUTLOOK = "outlook"
    RISKS = "risks"
    DRIVERS = "drivers"


DEFAULT_COMPANY_SECTIONS = (
    ContextSectionName.COMPANY_FACTS,
    ContextSectionName.MARKET_RISK,
    ContextSectionName.SECTOR,
    ContextSectionName.MACRO,
    ContextSectionName.EVENTS,
)


class IntelligenceContextRequest(BaseModel):
    symbol: str = Field(min_length=1, max_length=30)
    scope: ContextScope = ContextScope.COMPANY_INTELLIGENCE
    sections: tuple[ContextSectionName, ...] | None = None
    portfolio_id: str | None = None
    research_purpose: ResearchPurpose | None = None
    question: str | None = Field(default=None, min_length=1, max_length=2000)
    rag_limit: int = Field(default=5, ge=1, le=8)
    event_limit: int = Field(default=8, ge=1, le=100)

    @model_validator(mode="after")
    def validate_scope(self) -> "IntelligenceContextRequest":
        self.symbol = self.symbol.strip().upper()
        if self.scope == ContextScope.COMPANY_INTELLIGENCE and self.portfolio_id is not None:
            raise ValueError("Company Intelligence cannot include a portfolio")
        if self.scope in {ContextScope.PORTFOLIO_RELEVANCE, ContextScope.SECURITY_FIT} and not self.portfolio_id:
            raise ValueError(f"{self.scope.value} requires one selected portfolio")
        requested = set(self.resolved_sections())
        personalized = {ContextSectionName.PORTFOLIO, ContextSectionName.IPS}
        if self.scope == ContextScope.COMPANY_INTELLIGENCE and requested & personalized:
            raise ValueError("Company Intelligence cannot request portfolio or IPS sections")
        if self.scope == ContextScope.SECURITY_FIT and not personalized.issubset(requested):
            raise ValueError("Security Fit requires portfolio and IPS sections")
        return self

    def resolved_sections(self) -> tuple[ContextSectionName, ...]:
        if self.sections is not None:
            return tuple(dict.fromkeys(self.sections))
        base = list(DEFAULT_COMPANY_SECTIONS)
        if self.scope != ContextScope.COMPANY_INTELLIGENCE:
            base = [ContextSectionName.PORTFOLIO, ContextSectionName.IPS, *base]
        if self.question or self.research_purpose:
            base.append(ContextSectionName.RAG_EVIDENCE)
        return tuple(base)


class EvidenceReference(BaseModel):
    evidence_id: str
    classification: Literal[
        "structured_fact", "market_observation", "calculation", "event", "document_passage", "mandate"
    ]
    source: str
    source_url: str | None = None
    as_of: datetime | str | None = None
    underlying_id: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class ContextDeficiency(BaseModel):
    deficiency_id: str
    entity_type: str
    entity_key: str
    category: str
    observed_state: ContextState
    expected: dict[str, Any]
    reason: str
    urgency: Literal["low", "normal", "high"] = "normal"
    fingerprint: str


class ContextSection(BaseModel):
    name: ContextSectionName
    state: ContextState
    as_of: datetime | str | None = None
    data: Any = None
    evidence: list[EvidenceReference] = Field(default_factory=list)
    provenance: dict[str, Any] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)
    dependency_hash: str
    reused: bool = False


class ContextReceipt(BaseModel):
    contract_version: str = CONTEXT_CONTRACT_VERSION
    context_id: str
    built_at: datetime
    content_hash: str
    evidence_ids: list[str]
    calculation_runs: list[str] = Field(default_factory=list)
    section_states: dict[str, ContextState]
    dependency_hashes: dict[str, str]
    build_duration_ms: float
    section_duration_ms: dict[str, float]


class IntelligenceContext(BaseModel):
    context_id: str
    contract_version: str = CONTEXT_CONTRACT_VERSION
    scope: ContextScope
    symbol: str
    portfolio_id: str | None = None
    built_at: datetime
    status: Literal["ready", "degraded", "refreshing"]
    message: str | None = None
    sections: dict[str, ContextSection]
    deficiencies: list[ContextDeficiency]
    receipt: ContextReceipt


class IngestionWorkReference(BaseModel):
    work_id: str
    state: Literal[
        "queued", "running", "succeeded", "partial", "failed", "timed_out", "not_applicable"
    ]
    coordinator: str
