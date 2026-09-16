from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class AllocationRow(BaseModel):
    instrument_id: str
    symbol: str
    current_capital_weight: float
    proposed_capital_weight: float
    side: Literal["buy", "sell"] | None = None
    quantity: str | None = None
    gross_amount: str | None = None
    currency: str | None = None


class ArithmeticFundingCheck(BaseModel):
    status: Literal["accepted", "rejected"]
    errors: list[str] = Field(default_factory=list)


class IPSAllocationCheck(BaseModel):
    status: Literal["PASS", "BREACH", "NOT_EVALUATED"]
    violations: list[dict[str, object]] = Field(default_factory=list)
    not_evaluated: list[dict[str, object]] = Field(default_factory=list)


class PriceFreshnessCheck(BaseModel):
    status: Literal["current", "stale", "unavailable"]
    instruments: dict[str, object] = Field(default_factory=dict)


class ModeledGoalCheck(BaseModel):
    status: Literal["meets", "below", "unavailable"]
    required_return: float | None = None
    proposed_modeled_return: float | None = None
    shortfall: float | None = None
    method: str | None = None
    unit: Literal["annual_decimal_rate"] = "annual_decimal_rate"
    guaranteed: Literal[False] = False


class AllocationChecks(BaseModel):
    arithmetic_funding: ArithmeticFundingCheck | None = None
    ips_compliance: IPSAllocationCheck | None = None
    price_freshness: PriceFreshnessCheck | None = None
    modeled_goal: ModeledGoalCheck | None = None


class AllocationResult(BaseModel):
    status: Literal["accepted", "rejected", "unavailable", "not_requested"]
    verification_id: str | None = None
    rows: list[AllocationRow] = Field(default_factory=list)
    legs: list[dict[str, object]] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    error: dict[str, object] | None = None
    checks: AllocationChecks = Field(default_factory=AllocationChecks)
    evidence_readiness: dict[str, object] | None = None
    cost_note: str | None = None
    weight_unit: str = "fraction_of_total_capital"
    financial_state_mutated: bool = False


class ConversationCreate(BaseModel):
    title: str = Field(default="Portfolio research", min_length=1, max_length=255)
    portfolio_id: str | None = None


class AssistantMessageCreate(BaseModel):
    question: str = Field(min_length=1, max_length=8000)
    portfolio_id: str | None = None
    instrument_id: str | None = None
    provider: str | None = None
    model: str | None = None


class AssistantResponse(BaseModel):
    conversation_id: str
    message_id: str
    answer: str
    uncertainty: list[str]
    calculated_evidence: list[dict[str, object]]
    source_citations: list[dict[str, object]]
    freshness_warnings: list[str]
    tool_trace: list[dict[str, object]]
    synthesis: dict[str, object]
    context_contract_version: str | None = None
    context_status: str | None = None
    context_receipt: dict[str, object] | None = None
    refresh_request_id: str | None = None
    created_at: datetime

    @field_validator("synthesis")
    @classmethod
    def validate_allocation(cls, value):
        if value.get("allocation_check") is not None:
            value = {**value, "allocation_check": AllocationResult.model_validate(
                value["allocation_check"]
            ).model_dump(mode="json", exclude_none=True)}
        return value


class AssistantRunCreate(AssistantMessageCreate):
    client_request_id: str = Field(min_length=1, max_length=100)
    conversation_id: str | None = None
