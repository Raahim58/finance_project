from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class PortfolioCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    base_currency: str = Field(default="PKR", min_length=3, max_length=10)
    source_mode: str = Field(default="manual", pattern="^(manual|synced)$")
    provider_name: str = Field(default="ManualPortfolioProvider", min_length=1, max_length=80)


class PortfolioUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    base_currency: str | None = Field(default=None, min_length=3, max_length=10)
    source_mode: str | None = Field(default=None, pattern="^(manual|synced)$")
    provider_name: str | None = Field(default=None, min_length=1, max_length=80)


class PortfolioResponse(BaseModel):
    id: str
    name: str
    base_currency: str
    source_mode: str
    provider_name: str
    last_synced_at: datetime | None
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
    symbol: str = Field(min_length=1, max_length=30)
    transaction_type: str = Field(
        pattern="^(buy|sell|dividend|deposit|withdrawal|fee|manual_adjustment)$"
    )
    quantity: Decimal | None = Field(default=None, gt=0)
    price: Decimal | None = Field(default=None, ge=0)
    amount: Decimal
    transaction_date: date
    notes: str | None = None
    source: str = "manual"


class TransactionUpdate(BaseModel):
    transaction_type: str | None = Field(
        default=None, pattern="^(buy|sell|dividend|deposit|withdrawal|fee|manual_adjustment)$"
    )
    quantity: Decimal | None = Field(default=None, gt=0)
    price: Decimal | None = Field(default=None, ge=0)
    amount: Decimal | None = None
    transaction_date: date | None = None
    notes: str | None = None
    source: str | None = None


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
