from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Awaitable, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field


class RecommendationLabel(StrEnum):
    BUY_ADD = "Buy/Add"
    HOLD = "Hold"
    REDUCE = "Reduce"
    AVOID = "Avoid"
    INSUFFICIENT_EVIDENCE = "Insufficient Evidence"


class RecommendationHorizon(BaseModel):
    label: str = Field(min_length=1, max_length=120)
    source: Literal["ips", "user", "not_available"]


class ModelAnswer(BaseModel):
    """Internal transport. Only ``answer`` is displayed as the answer."""

    model_config = ConfigDict(extra="forbid")

    answer: str = Field(min_length=1, max_length=12_000)
    recommendation: RecommendationLabel | None = None
    confidence: Literal["High", "Medium", "Low"] | None = None
    horizon: RecommendationHorizon | None = None
    portfolio_id: str | None = None
    instrument_ids: list[str] = Field(default_factory=list, max_length=20)
    evidence_ids: list[str] = Field(default_factory=list, max_length=200)
    freshness_acknowledgements: list[str] = Field(default_factory=list, max_length=20)


class SectorCandidateSet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instrument_ids: list[str] = Field(default_factory=list, max_length=10)


class MarketCandidateSet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instrument_ids: list[str] = Field(default_factory=list, max_length=20)


@dataclass(frozen=True)
class ReasoningRequest:
    question: str
    mode: Literal["targeted", "market_wide"]
    portfolio_id: str | None
    portfolio_name: str | None
    history: list[dict[str, str]]
    grounded_context: dict[str, object]
    allowed_evidence_ids: set[str]
    allowed_instrument_ids: set[str]
    allowed_numeric_tokens: set[str] = field(default_factory=set)
    required_evidence_ids: set[str] = field(default_factory=set)
    freshness_warnings: list[str] = field(default_factory=list)
    sector_packets: dict[str, list[dict[str, object]]] = field(default_factory=dict)
    deepen_candidates: Callable[[list[str]], Awaitable[dict[str, object]]] | None = None


@dataclass(frozen=True)
class ReasoningInvocation:
    operation: str
    provider: str
    model: str
    status: Literal["success", "provider_error", "error"]
    input_bytes: int
    input_sha256: str
    latency_ms: int
    input_tokens: int | None = None
    output_tokens: int | None = None
    http_status: int | None = None
    error_type: str | None = None
    error_message: str | None = None
    provider_request_id: str | None = None
    response_excerpt: str | None = None


@dataclass(frozen=True)
class ReasoningResult:
    answer: str
    recommendation: RecommendationLabel | None
    confidence: Literal["High", "Medium", "Low"] | None
    horizon: RecommendationHorizon | None
    evidence_ids: list[str]
    instrument_ids: list[str]
    status: Literal["grounded", "unavailable"]
    provider: str | None
    model: str | None
    input_tokens: int = 0
    output_tokens: int = 0
    model_calls: int = 0
    failure_reason: str | None = None
    validation_errors: list[str] = field(default_factory=list)
    repaired: bool = False
    trace: list[dict[str, object]] = field(default_factory=list)
    invocations: list[ReasoningInvocation] = field(default_factory=list)
