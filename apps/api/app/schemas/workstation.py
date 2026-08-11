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


class RiskAssessment(BaseModel):
    capacity: Literal["low", "moderate", "high"] | None = None
    willingness: Literal["low", "moderate", "high"] | None = None
    reconciled_tolerance: Literal["low", "moderate", "high"] | None = None
    confirmed_tolerance: Literal["low", "moderate", "high"] | None = None
    available: bool
    diagnostics: list[str] = Field(default_factory=list)


class DatedContribution(BaseModel):
    contribution_date: date
    amount: float = Field(gt=0)


class IPSDraft(BaseModel):
    constraints: dict[str, object] = Field(default_factory=dict)
    starting_capital: float | None = Field(default=None, gt=0)
    target_value: float | None = Field(default=None, gt=0)
    horizon_years: float | None = Field(default=None, gt=0)
    annual_contribution: float = Field(default=0, ge=0)
    goal: str | None = Field(default=None, max_length=500)
    benchmark_symbol: str | None = Field(default=None, max_length=30)
    valuation_date: date | None = None
    target_date: date | None = None
    dated_contributions: list[DatedContribution] = Field(default_factory=list)
    inflation_rate: float | None = Field(default=None, gt=-1)
    target_value_is_real: bool = False
    risk_capacity: Literal["low", "moderate", "high"] | None = None
    risk_willingness: Literal["low", "moderate", "high"] | None = None
    overall_risk_tolerance: Literal["low", "moderate", "high"] | None = None
    loss_budget: float | None = Field(default=None, ge=0, le=1)
    liquidity_requirement: float | None = Field(default=None, ge=0)
    allowed_asset_types: list[str] | None = None
    allowed_currencies: list[str] | None = None
    shariah_only: bool | None = None
    leverage_allowed: bool | None = None
    derivatives_allowed: bool | None = None
    tax_notes: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def validate_goal_dates(self):
        if self.target_date and self.valuation_date and self.target_date <= self.valuation_date:
            raise ValueError("target_date must be after valuation_date")
        if self.target_value_is_real and self.inflation_rate is None:
            raise ValueError("A real target value requires an inflation_rate assumption")
        return self


class IPSVersionResponse(BaseModel):
    id: str
    version: int
    status: str
    constraints: dict[str, object]
    required_return: float | None
    required_return_analysis: dict[str, object] = Field(default_factory=dict)
    confirmed_at: datetime | None


class RequiredReturnAnalysis(BaseModel):
    available: bool
    annual_rate: float | None = None
    calculation_type: str | None = None
    assumptions: dict[str, object] = Field(default_factory=dict)
    diagnostics: list[str] = Field(default_factory=list)


class IPSComplianceResponse(BaseModel):
    portfolio_id: str
    ips_version_id: str | None
    compliant: bool
    violations: list[dict[str, object]]
    evaluated_at: datetime


class AssumptionSecurity(BaseModel):
    symbol: str
    expected_return: float | None = None
    expected_return_method: str | None = None
    volatility: float | None = None
    beta: float | None = None
    capm_return: float | None = None
    realized_return: float | None = None
    diagnostics: list[str] = Field(default_factory=list)


class CapitalMarketAssumptionsResponse(BaseModel):
    portfolio_id: str
    data_cutoff: date
    sample_start: date
    sample_size: int
    annualization: int
    estimator: dict[str, object]
    risk_free: dict[str, object] | None = None
    benchmark: dict[str, object]
    securities: list[AssumptionSecurity]
    covariance: list[list[float]]
    correlation: list[list[float]]
    provenance: list[dict[str, object]]
    warnings: list[str] = Field(default_factory=list)


class FrontierPoint(BaseModel):
    expected_return: float
    volatility: float
    weights: dict[str, float]


class EfficientFrontierResponse(BaseModel):
    portfolio_id: str
    data_cutoff: date
    estimator: str
    points: list[FrontierPoint]
    markers: dict[str, FrontierPoint | None]
    assumptions: dict[str, object]
    warnings: list[str] = Field(default_factory=list)


class CapmPoint(BaseModel):
    symbol: str
    beta: float
    realized_return: float
    capm_return: float
    jensen_alpha: float


class CapmSmlResponse(BaseModel):
    available: bool
    portfolio_id: str
    data_cutoff: date
    risk_free_rate: float | None = None
    market_return: float | None = None
    benchmark_symbol: str | None = None
    securities: list[CapmPoint] = Field(default_factory=list)
    sml: list[dict[str, float]] = Field(default_factory=list)
    diagnostics: list[str] = Field(default_factory=list)


class RollingRiskPoint(BaseModel):
    date: date
    volatility: float
    sharpe: float | None = None
    drawdown: float
    beta: float | None = None


class RollingRiskResponse(BaseModel):
    portfolio_id: str
    window: int
    points: list[RollingRiskPoint]
    diagnostics: list[str] = Field(default_factory=list)


class DistributionBin(BaseModel):
    lower: float
    upper: float
    count: int


class ReturnDistributionResponse(BaseModel):
    portfolio_id: str
    sample_size: int
    bins: list[DistributionBin]
    var_95: float | None = None
    es_95: float | None = None
    var_99: float | None = None
    es_99: float | None = None
    skewness: float | None = None
    excess_kurtosis: float | None = None
    diagnostics: list[str] = Field(default_factory=list)


class PortfolioComparisonRequest(BaseModel):
    target_weights: dict[str, float] = Field(min_length=1)
    label: str = Field(default="Proposed portfolio", max_length=160)


class ComparisonMetric(BaseModel):
    key: str
    label: str
    unit: str
    current: float | None = None
    proposed: float | None = None
    delta: float | None = None
    preferred_direction: Literal["higher", "lower", "neutral"]
    availability_note: str | None = None


class PortfolioComparisonResponse(BaseModel):
    portfolio_id: str
    label: str
    data_cutoff: date
    assumptions: dict[str, object]
    current_weights: dict[str, float]
    proposed_weights: dict[str, float]
    metrics: list[ComparisonMetric]
    current_risk_contributions: dict[str, float]
    proposed_risk_contributions: dict[str, float]
    current_compliance: dict[str, object]
    proposed_compliance: dict[str, object]
    trade_offs: list[dict[str, object]]
    warnings: list[str] = Field(default_factory=list)


class RiskBudgetItem(BaseModel):
    symbol: str
    capital_weight: float
    component_risk: float
    percentage_risk: float
    target_risk: float | None = None
    residual: float | None = None


class RiskBudgetResponse(BaseModel):
    portfolio_id: str
    data_cutoff: date
    items: list[RiskBudgetItem]
    total_percentage_risk: float
    residual_error: float | None = None
    diagnostics: list[str] = Field(default_factory=list)


class OptimizerRequest(BaseModel):
    objective: Literal["minimum_variance", "target_return_minimum_variance", "target_volatility_maximum_return", "target_beta", "max_sharpe", "risk_parity", "risk_budget"] = "minimum_variance"
    expected_return_method: Literal["capm", "historical_shrunk", "user_model"] | None = None
    expected_return_assumptions: dict[str, float] | None = None
    target_return: float | None = None
    target_volatility: float | None = Field(default=None, gt=0)
    target_beta: float | None = None
    beta_assumptions: dict[str, float] | None = None
    risk_budgets: dict[str, float] | None = None
    risk_free_rate: float = 0.0
    benchmark_symbol: str | None = Field(default=None, max_length=30)
    risk_free_series_key: str | None = Field(default=None, max_length=160)
    start_date: date | None = None
    end_date: date | None = None
    covariance_shrinkage: float = Field(default=0.20, ge=0, le=1)
    expected_return_shrinkage: float = Field(default=0.50, ge=0, le=1)
    minimum_weight: float = Field(default=0, ge=0, le=1)
    maximum_weight: float = Field(default=1, gt=0, le=1)
    include_cash: bool = False
    minimum_cash_weight: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def validate_method(self):
        if self.objective == "minimum_variance" and self.expected_return_method is not None:
            return self
        if self.objective in {"target_return_minimum_variance", "target_volatility_maximum_return", "max_sharpe"} and self.expected_return_method is None:
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
    allocation_set_id: str | None = None


class PortfolioQuantResponse(BaseModel):
    data_cutoff: date
    symbols: list[str]
    sample_size: int
    annualization: int
    covariance_shrinkage: float
    portfolio: dict[str, object]
    benchmark: dict[str, object] = Field(default_factory=dict)
    rolling: dict[str, object] = Field(default_factory=dict)
    covariance: list[list[float]] = Field(default_factory=list)
    correlation: list[list[float]] = Field(default_factory=list)
    risk_contributions: dict[str, float] = Field(default_factory=dict)
    run_id: str | None = None
    warnings: list[str]


class ScenarioRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    scenario_type: Literal["sensitivity", "hypothetical"] = "hypothetical"
    shocks: dict[str, float] = Field(default_factory=dict)
    sector_shocks: dict[str, float] = Field(default_factory=dict)
    factor_shocks: dict[str, float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_shocks(self):
        if not self.shocks and not self.sector_shocks and not self.factor_shocks:
            raise ValueError("At least one instrument, sector, or factor shock is required")
        return self


class RebalanceRequest(BaseModel):
    target_weights: dict[str, float] = Field(min_length=1)
    minimum_trade_value: float = Field(default=0, ge=0)
    fee_rate: float = Field(default=0, ge=0)
    tax_rate: float = Field(default=0, ge=0)
    allow_sells: bool = True
    locked_symbols: list[str] = Field(default_factory=list)


class RebalanceResponse(BaseModel):
    portfolio_id: str
    data_cutoff: date | None
    trades: list[dict[str, object]]
    residual_cash: float
    warnings: list[str]
    post_trade_validation: dict[str, object] = Field(default_factory=dict)
    risk_impact: dict[str, object] = Field(default_factory=dict)


class ScenarioResponse(BaseModel):
    id: str
    name: str
    data_cutoff: date
    shocks: dict[str, float]
    portfolio_value: float
    stressed_portfolio_value: float
    pnl: float
    pnl_percent: float
    positions: list[dict[str, object]]
    sector_contributions: dict[str, float] = Field(default_factory=dict)
    compliance: dict[str, object] = Field(default_factory=dict)
    assumptions: list[str]


class MonitoringRuleCreate(BaseModel):
    rule_type: Literal["position_weight", "concentration", "stale_data", "drawdown", "volatility", "var", "liquidity", "event", "ingestion_failure", "beta_shift", "correlation_shift", "risk_budget", "scenario_breach"]
    threshold: dict[str, object]
    deduplication_window_minutes: int = Field(default=1440, ge=1, le=525600)


class MonitoringRuleResponse(BaseModel):
    id: str
    portfolio_id: str
    rule_type: str
    threshold: dict[str, object]
    enabled: bool
    deduplication_window_minutes: int = 1440


class RecommendationResponse(BaseModel):
    id: str
    portfolio_id: str
    trigger: str
    evidence: dict[str, object]
    ips_violation: object = Field(default_factory=dict)
    assumptions: dict[str, object] = Field(default_factory=dict)
    expected_effect: dict[str, object] = Field(default_factory=dict)
    uncertainty: dict[str, object] = Field(default_factory=dict)
    freshness: dict[str, object] = Field(default_factory=dict)
    message: str
    status: str
    created_at: datetime
