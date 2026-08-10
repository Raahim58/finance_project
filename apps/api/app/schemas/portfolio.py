from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class PortfolioCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    base_currency: str = Field(default="PKR", min_length=3, max_length=10)
    source_mode: str = Field(default="manual", pattern="^(manual|synced)$")
    provider_name: str = Field(default="ManualPortfolioProvider", min_length=1, max_length=80)
    description: str | None = None
    goal_summary: str | None = None


class PortfolioUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    base_currency: str | None = Field(default=None, min_length=3, max_length=10)
    source_mode: str | None = Field(default=None, pattern="^(manual|synced)$")
    provider_name: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = None
    goal_summary: str | None = None


class PortfolioResponse(BaseModel):
    id: str
    name: str
    base_currency: str
    source_mode: str
    provider_name: str
    last_synced_at: datetime | None
    description: str | None
    goal_summary: str | None
    is_default: bool
    archived_at: datetime | None
    history_start: date | None
    history_complete: bool
    selected_ips_version_id: str | None
    created_at: datetime
    updated_at: datetime


class HoldingCreate(BaseModel):
    symbol: str = Field(min_length=1, max_length=30)
    quantity: Decimal = Field(gt=0)
    average_cost: Decimal = Field(ge=0)


class HoldingUpdate(BaseModel):
    quantity: Decimal | None = Field(default=None, gt=0)
    average_cost: Decimal | None = Field(default=None, ge=0)


class HoldingResponse(BaseModel):
    id: str
    portfolio_id: str
    company_id: str
    symbol: str
    quantity: Decimal
    average_cost: Decimal
    created_at: datetime
    updated_at: datetime


class TransactionCreate(BaseModel):
    symbol: str = Field(default="CASH", min_length=1, max_length=30)
    transaction_type: str = Field(
        pattern="^(buy|sell|dividend|deposit|withdrawal|fee|tax|opening_balance|manual_adjustment|corporate_action)$"
    )
    quantity: Decimal | None = Field(default=None, gt=0)
    price: Decimal | None = Field(default=None, ge=0)
    amount: Decimal
    transaction_date: date
    notes: str | None = None
    source: str = "manual"
    currency: str = Field(default="PKR", min_length=3, max_length=10)
    fees: Decimal = Field(default=Decimal("0"), ge=0)
    taxes: Decimal = Field(default=Decimal("0"), ge=0)
    settlement_date: date | None = None
    external_id: str | None = Field(default=None, max_length=120)


class TransactionUpdate(BaseModel):
    transaction_type: str | None = Field(
        default=None, pattern="^(buy|sell|dividend|deposit|withdrawal|fee|tax|opening_balance|manual_adjustment|corporate_action)$"
    )
    quantity: Decimal | None = Field(default=None, gt=0)
    price: Decimal | None = Field(default=None, ge=0)
    amount: Decimal | None = None
    transaction_date: date | None = None
    notes: str | None = None
    source: str | None = None
    fees: Decimal | None = Field(default=None, ge=0)
    taxes: Decimal | None = Field(default=None, ge=0)
    settlement_date: date | None = None
    external_id: str | None = Field(default=None, max_length=120)


class TransactionResponse(BaseModel):
    id: str
    portfolio_id: str
    company_id: str | None
    symbol: str
    transaction_type: str
    quantity: Decimal | None
    price: Decimal | None
    amount: Decimal
    transaction_date: date
    notes: str | None
    source: str
    currency: str
    fees: Decimal
    taxes: Decimal
    settlement_date: date | None
    external_id: str | None
    reversal_of_id: str | None
    created_at: datetime


class HoldingSummary(BaseModel):
    holding_id: str
    symbol: str
    name: str
    sector: str
    quantity: Decimal
    average_cost: Decimal
    latest_price: Decimal | None
    latest_price_date: date | None
    cost_basis: Decimal
    market_value: Decimal
    unrealized_gain_loss: Decimal
    unrealized_gain_loss_percent: Decimal | None
    day_change: Decimal | None
    day_change_percent: Decimal | None
    data_source: str | None


class PortfolioSummaryResponse(BaseModel):
    portfolio: PortfolioResponse
    total_value: Decimal
    cost_basis: Decimal
    unrealized_gain_loss: Decimal
    unrealized_gain_loss_percent: Decimal | None
    day_change: Decimal
    day_change_percent: Decimal | None
    cash_balance: Decimal
    holdings: list[HoldingSummary]
    data_freshness_date: date | None
    data_source: str | None


class SectorExposureResponse(BaseModel):
    sector: str
    market_value: Decimal
    weight_percent: Decimal


class CompanyExposureResponse(BaseModel):
    symbol: str
    name: str
    market_value: Decimal
    weight_percent: Decimal


class PortfolioExposureResponse(BaseModel):
    total_value: Decimal
    by_sector: list[SectorExposureResponse]
    by_company: list[CompanyExposureResponse]


class PortfolioPerformancePoint(BaseModel):
    value_date: date
    total_value: Decimal
    day_change: Decimal
    day_change_percent: Decimal | None


class PortfolioRiskFlag(BaseModel):
    severity: str
    code: str
    message: str
    value: Decimal | None = None


class PortfolioRiskFlagsResponse(BaseModel):
    flags: list[PortfolioRiskFlag]


class PortfolioDuplicateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    include_positions: bool = False


class AllocationItemInput(BaseModel):
    symbol: str = Field(min_length=1, max_length=30)
    target_weight: Decimal = Field(ge=0, le=1)
    locked: bool = False
    is_cash: bool = False


class AllocationSetCreate(BaseModel):
    kind: str = Field(pattern="^(sandbox|target|optimized)$")
    items: list[AllocationItemInput] = Field(min_length=1)
    base_value: Decimal | None = Field(default=None, ge=0)
    assumptions: dict[str, object] = Field(default_factory=dict)


class AllocationItemResponse(BaseModel):
    id: str
    symbol: str
    instrument_id: str | None
    target_weight: Decimal
    target_amount: Decimal | None
    target_quantity: Decimal | None
    locked: bool
    is_cash: bool


class AllocationSetResponse(BaseModel):
    id: str
    portfolio_id: str
    kind: str
    version: int
    status: str
    base_value: Decimal | None
    assumptions: dict[str, object]
    items: list[AllocationItemResponse]
    created_at: datetime


class CashBalanceResponse(BaseModel):
    currency: str
    balance: Decimal


class PositionResponse(BaseModel):
    instrument_id: str
    symbol: str
    quantity: Decimal
    average_cost: Decimal
