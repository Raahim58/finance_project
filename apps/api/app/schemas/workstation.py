from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class VersionDraft(BaseModel):
    data: dict[str, object] = Field(default_factory=dict)


class ProfileVersionResponse(BaseModel):
    id: str
    version: int
    status: str
    data: dict[str, object]
    confirmed_at: datetime | None


class IPSDraft(BaseModel):
    constraints: dict[str, object] = Field(default_factory=dict)
    starting_capital: float | None = Field(default=None, gt=0)
    target_value: float | None = Field(default=None, gt=0)
    horizon_years: float | None = Field(default=None, gt=0)


class IPSVersionResponse(BaseModel):
    id: str
    version: int
    status: str
    constraints: dict[str, object]
    required_return: float | None
    confirmed_at: datetime | None


class OptimizerRequest(BaseModel):
    objective: Literal["minimum_variance", "target_return_minimum_variance"] = "minimum_variance"
    expected_return_method: Literal["capm", "historical_shrunk", "user_model"] | None = None
    expected_return_assumptions: dict[str, float] | None = None
    target_return: float | None = None
    start_date: date | None = None
    end_date: date | None = None
    covariance_shrinkage: float = Field(default=0.20, ge=0, le=1)
    expected_return_shrinkage: float = Field(default=0.50, ge=0, le=1)
    minimum_weight: float = Field(default=0, ge=0, le=1)
    maximum_weight: float = Field(default=1, gt=0, le=1)

    @model_validator(mode="after")
    def validate_method(self):
        if self.objective == "minimum_variance" and self.expected_return_method is not None:
            return self
        if self.objective != "minimum_variance" and self.expected_return_method is None:
            raise ValueError("Expected-return methodology is required for a return-targeted objective")
        if self.expected_return_method == "user_model" and not self.expected_return_assumptions:
            raise ValueError("user_model requires explicit symbol assumptions")
        return self


class OptimizerResponse(BaseModel):
    id: str
    status: str
    objective: str
    expected_return_method: str | None
    data_cutoff: date
    symbols: list[str]
    weights: dict[str, float]
    expected_return: float | None
    volatility: float | None
    diagnostics: dict[str, object]
    assumptions: dict[str, object]


class PortfolioQuantResponse(BaseModel):
    data_cutoff: date
    symbols: list[str]
    sample_size: int
    annualization: int
    covariance_shrinkage: float
    portfolio: dict[str, float | int]
    warnings: list[str]


class ScenarioRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    shocks: dict[str, float] = Field(min_length=1)


class ScenarioResponse(BaseModel):
    id: str
    name: str
    data_cutoff: date
    shocks: dict[str, float]
    portfolio_value: float
    pnl: float
    pnl_percent: float
    positions: list[dict[str, object]]
    assumptions: list[str]


class MonitoringRuleCreate(BaseModel):
    rule_type: Literal["position_weight", "stale_data", "drawdown"]
    threshold: dict[str, object]


class MonitoringRuleResponse(BaseModel):
    id: str
    portfolio_id: str
    rule_type: str
    threshold: dict[str, object]
    enabled: bool


class RecommendationResponse(BaseModel):
    id: str
    portfolio_id: str
    trigger: str
    evidence: dict[str, object]
    message: str
    status: str
    created_at: datetime
