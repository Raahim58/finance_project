from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field, model_validator


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
    amount: Decimal = Field(ge=0)
    transaction_date: date
    notes: str | None = None
    source: str = "manual"
    currency: str = Field(default="PKR", min_length=3, max_length=10)
    fees: Decimal = Field(default=Decimal("0"), ge=0)
    taxes: Decimal = Field(default=Decimal("0"), ge=0)
    settlement_date: date | None = None
    external_id: str | None = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def validate_financial_contract(self):
        transaction_type = self.transaction_type
        symbol = self.symbol.strip().upper()
        instrument_types = {"buy", "sell", "dividend", "manual_adjustment", "corporate_action"}
        cash_types = {"deposit", "withdrawal", "fee", "tax"}

        if transaction_type in instrument_types and symbol == "CASH":
            raise ValueError(f"{transaction_type} requires an instrument symbol")
        if transaction_type in cash_types and symbol != "CASH":
            raise ValueError(f"{transaction_type} must use symbol CASH")
        if transaction_type in {"buy", "sell"}:
            if self.quantity is None or self.price is None or self.price <= 0:
                raise ValueError(f"{transaction_type} requires positive quantity and price")
            expected = self.quantity * self.price
            tolerance = max(Decimal("0.01"), expected * Decimal("0.0001"))
            if abs(self.amount - expected) > tolerance:
                raise ValueError("amount must equal quantity × price within 0.01% (minimum PKR 0.01)")
        elif transaction_type == "dividend":
            if self.amount <= 0:
                raise ValueError("dividend requires a positive amount")
        elif transaction_type in cash_types:
            if self.amount <= 0:
                raise ValueError(f"{transaction_type} requires a positive amount")
            if self.quantity is not None or self.price is not None:
                raise ValueError(f"{transaction_type} cannot include quantity or price")
        elif transaction_type == "corporate_action":
            if self.quantity is None or self.quantity <= 0 or self.amount != 0:
                raise ValueError("corporate_action requires a positive split multiplier and zero amount")
        elif transaction_type == "manual_adjustment":
            if self.quantity is None or self.price is None or self.amount != 0:
                raise ValueError("manual_adjustment requires quantity, price, and zero amount")
        elif transaction_type == "opening_balance":
            if symbol == "CASH":
                if self.amount <= 0 or self.quantity is not None or self.price is not None:
                    raise ValueError("cash opening_balance requires a positive amount only")
            elif self.quantity is None or self.price is None or self.amount != 0:
                raise ValueError("instrument opening_balance requires quantity, price, and zero amount")

        if self.settlement_date is not None:
            if transaction_type not in {"buy", "sell"}:
                raise ValueError("settlement_date is only valid for buy and sell transactions")
            if self.settlement_date < self.transaction_date:
                raise ValueError("settlement_date cannot precede transaction_date")
        return self


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
    artifact_id: str | None = None
    quality_status: str | None = None
    adjustment_state: str | None = None


class PortfolioSummaryResponse(BaseModel):
    portfolio: PortfolioResponse
    total_value: Decimal
    cost_basis: Decimal
    unrealized_gain_loss: Decimal
    unrealized_gain_loss_percent: Decimal | None
    net_external_contributions: Decimal
    total_gain_loss: Decimal
    day_change: Decimal
    day_change_percent: Decimal | None
    cash_balance: Decimal
    holdings: list[HoldingSummary]
    data_freshness_date: date | None
    data_source: str | None
    valuation_complete: bool = True
    unpriced_symbols: list[str] = Field(default_factory=list)
    valuation_note: str | None = None


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
    external_cash_flow: Decimal
    value_change: Decimal
    day_change: Decimal
    day_change_percent: Decimal | None
    cumulative_twr_percent: Decimal | None


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
