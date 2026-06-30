from collections import defaultdict
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.market import Company, MarketPrice
from app.models.portfolio import Portfolio, PortfolioHolding, PortfolioTransaction
from app.models.user import User
from app.services.portfolio_providers import describe_portfolio_source, get_portfolio_provider
from app.schemas.portfolio import (
    CompanyExposureResponse,
    HoldingCreate,
    HoldingResponse,
    HoldingSummary,
    HoldingUpdate,
    PortfolioCreate,
    PortfolioExposureResponse,
    PortfolioPerformancePoint,
    PortfolioResponse,
    PortfolioRiskFlag,
    PortfolioRiskFlagsResponse,
    PortfolioSummaryResponse,
    PortfolioUpdate,
    SectorExposureResponse,
    TransactionCreate,
    TransactionResponse,
    TransactionUpdate,
)


def money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def percent(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def serialize_portfolio(portfolio: Portfolio) -> PortfolioResponse:
    source_mode, provider_name = describe_portfolio_source(portfolio)
    return PortfolioResponse(
        id=portfolio.id,
        name=portfolio.name,
        base_currency=portfolio.base_currency,
        source_mode=source_mode,
        provider_name=provider_name,
        last_synced_at=portfolio.last_synced_at,
        created_at=portfolio.created_at,
        updated_at=portfolio.updated_at,
    )


def serialize_holding(holding: PortfolioHolding) -> HoldingResponse:
    return HoldingResponse(
        id=holding.id,
        portfolio_id=holding.portfolio_id,
        company_id=holding.company_id,
        symbol=holding.symbol,
        quantity=holding.quantity,
        average_cost=holding.average_cost,
        created_at=holding.created_at,
        updated_at=holding.updated_at,
    )


def serialize_transaction(transaction: PortfolioTransaction) -> TransactionResponse:
    return TransactionResponse(
        id=transaction.id,
        portfolio_id=transaction.portfolio_id,
        company_id=transaction.company_id,
        symbol=transaction.symbol,
        transaction_type=transaction.transaction_type,
        quantity=transaction.quantity,
        price=transaction.price,
        amount=transaction.amount,
        transaction_date=transaction.transaction_date,
        notes=transaction.notes,
        source=transaction.source,
        created_at=transaction.created_at,
    )


def get_portfolio_or_404(db: Session, user: User, portfolio_id: str) -> Portfolio:
    portfolio = db.scalar(
        select(Portfolio).where(Portfolio.id == portfolio_id, Portfolio.user_id == user.id)
    )
    if not portfolio:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Portfolio not found")
    return portfolio


def get_holding_or_404(db: Session, user: User, holding_id: str) -> PortfolioHolding:
    holding = db.scalar(
        select(PortfolioHolding)
        .join(Portfolio, Portfolio.id == PortfolioHolding.portfolio_id)
        .where(PortfolioHolding.id == holding_id, Portfolio.user_id == user.id)
    )
    if not holding:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Holding not found")
    return holding


def get_transaction_or_404(db: Session, user: User, transaction_id: str) -> PortfolioTransaction:
    transaction = db.scalar(
        select(PortfolioTransaction)
        .join(Portfolio, Portfolio.id == PortfolioTransaction.portfolio_id)
        .where(PortfolioTransaction.id == transaction_id, Portfolio.user_id == user.id)
    )
    if not transaction:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")
    return transaction


def get_company_by_symbol_or_404(db: Session, symbol: str) -> Company:
    company = db.scalar(
        select(Company).where(func.upper(Company.symbol) == symbol.upper(), Company.is_active.is_(True))
    )
    if not company:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")
    return company


def latest_price_for_symbol(db: Session, symbol: str) -> MarketPrice | None:
    return db.scalar(
        select(MarketPrice)
        .where(func.upper(MarketPrice.symbol) == symbol.upper())
        .order_by(MarketPrice.trade_date.desc())
        .limit(1)
    )


def price_for_symbol_on_or_before(db: Session, symbol: str, target_date: date) -> MarketPrice | None:
    return db.scalar(
        select(MarketPrice)
        .where(func.upper(MarketPrice.symbol) == symbol.upper(), MarketPrice.trade_date <= target_date)
        .order_by(MarketPrice.trade_date.desc())
        .limit(1)
    )


def list_portfolios(db: Session, user: User) -> list[PortfolioResponse]:
    rows = db.scalars(
        select(Portfolio).where(Portfolio.user_id == user.id).order_by(Portfolio.created_at.asc())
    ).all()
    return [serialize_portfolio(row) for row in rows]


def create_portfolio(db: Session, user: User, payload: PortfolioCreate) -> PortfolioResponse:
    provider = get_portfolio_provider(payload.source_mode, payload.provider_name)
    portfolio = Portfolio(
        user_id=user.id,
        name=payload.name,
        base_currency=payload.base_currency.upper(),
        source_mode=provider.source_mode,
        provider_name=provider.name,
    )
    db.add(portfolio)
    db.commit()
    db.refresh(portfolio)
    return serialize_portfolio(portfolio)


def update_portfolio(
    db: Session, user: User, portfolio_id: str, payload: PortfolioUpdate
) -> PortfolioResponse:
    portfolio = get_portfolio_or_404(db, user, portfolio_id)
    data = payload.model_dump(exclude_unset=True)
    if "name" in data and data["name"] is not None:
        portfolio.name = data["name"]
    if "base_currency" in data and data["base_currency"] is not None:
        portfolio.base_currency = data["base_currency"].upper()
    if "source_mode" in data and data["source_mode"] is not None:
        provider = get_portfolio_provider(data["source_mode"], data.get("provider_name") or portfolio.provider_name)
        portfolio.source_mode = provider.source_mode
        portfolio.provider_name = provider.name
    elif "provider_name" in data and data["provider_name"] is not None:
        provider = get_portfolio_provider(portfolio.source_mode, data["provider_name"])
        portfolio.provider_name = provider.name
    db.add(portfolio)
    db.commit()
    db.refresh(portfolio)
    return serialize_portfolio(portfolio)


def delete_portfolio(db: Session, user: User, portfolio_id: str) -> None:
    portfolio = get_portfolio_or_404(db, user, portfolio_id)
    db.delete(portfolio)
    db.commit()


def add_holding(db: Session, user: User, portfolio_id: str, payload: HoldingCreate) -> HoldingResponse:
    portfolio = get_portfolio_or_404(db, user, portfolio_id)
    company = get_company_by_symbol_or_404(db, payload.symbol)
    existing = db.scalar(
        select(PortfolioHolding).where(
            PortfolioHolding.portfolio_id == portfolio.id,
            func.upper(PortfolioHolding.symbol) == company.symbol.upper(),
        )
    )
    if existing:
        existing.quantity = payload.quantity
        existing.average_cost = payload.average_cost
        db.add(existing)
        db.commit()
        db.refresh(existing)
        return serialize_holding(existing)

    holding = PortfolioHolding(
        portfolio_id=portfolio.id,
        company_id=company.id,
        symbol=company.symbol,
        quantity=payload.quantity,
        average_cost=payload.average_cost,
    )
    db.add(holding)
    db.commit()
    db.refresh(holding)
    return serialize_holding(holding)


def list_holdings(db: Session, user: User, portfolio_id: str) -> list[HoldingResponse]:
    portfolio = get_portfolio_or_404(db, user, portfolio_id)
    rows = db.scalars(
        select(PortfolioHolding)
        .where(PortfolioHolding.portfolio_id == portfolio.id)
        .order_by(PortfolioHolding.symbol.asc())
    ).all()
    return [serialize_holding(row) for row in rows]


def update_holding(db: Session, user: User, holding_id: str, payload: HoldingUpdate) -> HoldingResponse:
    holding = get_holding_or_404(db, user, holding_id)
    data = payload.model_dump(exclude_unset=True)
    if "quantity" in data and data["quantity"] is not None:
        holding.quantity = data["quantity"]
    if "average_cost" in data and data["average_cost"] is not None:
        holding.average_cost = data["average_cost"]
    db.add(holding)
    db.commit()
    db.refresh(holding)
    return serialize_holding(holding)


def delete_holding(db: Session, user: User, holding_id: str) -> None:
    holding = get_holding_or_404(db, user, holding_id)
    db.delete(holding)
    db.commit()


def add_transaction(
    db: Session, user: User, portfolio_id: str, payload: TransactionCreate
) -> TransactionResponse:
    portfolio = get_portfolio_or_404(db, user, portfolio_id)
    company = db.scalar(
        select(Company).where(func.upper(Company.symbol) == payload.symbol.upper(), Company.is_active.is_(True))
    )
    transaction = PortfolioTransaction(
        portfolio_id=portfolio.id,
        company_id=company.id if company else None,
        symbol=company.symbol if company else payload.symbol.upper(),
        transaction_type=payload.transaction_type,
        quantity=payload.quantity,
        price=payload.price,
        amount=payload.amount,
        transaction_date=payload.transaction_date,
        notes=payload.notes,
        source=payload.source,
    )
    db.add(transaction)
    db.commit()
    db.refresh(transaction)
    return serialize_transaction(transaction)


def list_transactions(db: Session, user: User, portfolio_id: str) -> list[TransactionResponse]:
    portfolio = get_portfolio_or_404(db, user, portfolio_id)
    rows = db.scalars(
        select(PortfolioTransaction)
        .where(PortfolioTransaction.portfolio_id == portfolio.id)
        .order_by(PortfolioTransaction.transaction_date.desc(), PortfolioTransaction.created_at.desc())
    ).all()
    return [serialize_transaction(row) for row in rows]


def update_transaction(
    db: Session, user: User, transaction_id: str, payload: TransactionUpdate
) -> TransactionResponse:
    transaction = get_transaction_or_404(db, user, transaction_id)
    data = payload.model_dump(exclude_unset=True)
    for key, value in data.items():
        if value is not None:
            setattr(transaction, key, value)
    db.add(transaction)
    db.commit()
    db.refresh(transaction)
    return serialize_transaction(transaction)


def delete_transaction(db: Session, user: User, transaction_id: str) -> None:
    transaction = get_transaction_or_404(db, user, transaction_id)
    db.delete(transaction)
    db.commit()


def _holding_summaries(db: Session, portfolio: Portfolio) -> list[HoldingSummary]:
    holdings = db.scalars(
        select(PortfolioHolding)
        .where(PortfolioHolding.portfolio_id == portfolio.id)
        .order_by(PortfolioHolding.symbol.asc())
    ).all()
    summaries: list[HoldingSummary] = []
    for holding in holdings:
        company = db.get(Company, holding.company_id)
        latest = latest_price_for_symbol(db, holding.symbol)
        latest_price = latest.close if latest else None
        market_value = money(holding.quantity * latest_price) if latest_price is not None else Decimal("0")
        cost_basis = money(holding.quantity * holding.average_cost)
        unrealized = money(market_value - cost_basis)
        unrealized_percent = percent((unrealized / cost_basis) * Decimal("100")) if cost_basis else None
        day_change = money(holding.quantity * latest.change) if latest else None
        day_change_percent = latest.change_percent if latest else None
        summaries.append(
            HoldingSummary(
                holding_id=holding.id,
                symbol=holding.symbol,
                name=company.name if company else holding.symbol,
                sector=company.sector if company else "Unknown",
                quantity=holding.quantity,
                average_cost=holding.average_cost,
                latest_price=latest_price,
                latest_price_date=latest.trade_date if latest else None,
                cost_basis=cost_basis,
                market_value=market_value,
                unrealized_gain_loss=unrealized,
                unrealized_gain_loss_percent=unrealized_percent,
                day_change=day_change,
                day_change_percent=day_change_percent,
                data_source=latest.source if latest else None,
            )
        )
    return summaries


def get_portfolio_summary(db: Session, user: User, portfolio_id: str) -> PortfolioSummaryResponse:
    portfolio = get_portfolio_or_404(db, user, portfolio_id)
    holdings = _holding_summaries(db, portfolio)
    total_value = money(sum((holding.market_value for holding in holdings), Decimal("0")))
    cost_basis = money(sum((holding.cost_basis for holding in holdings), Decimal("0")))
    unrealized = money(total_value - cost_basis)
    day_change = money(
        sum((holding.day_change for holding in holdings if holding.day_change is not None), Decimal("0"))
    )
    previous_value = total_value - day_change
    return PortfolioSummaryResponse(
        portfolio=serialize_portfolio(portfolio),
        total_value=total_value,
        cost_basis=cost_basis,
        unrealized_gain_loss=unrealized,
        unrealized_gain_loss_percent=percent((unrealized / cost_basis) * Decimal("100")) if cost_basis else None,
        day_change=day_change,
        day_change_percent=percent((day_change / previous_value) * Decimal("100")) if previous_value else None,
        cash_balance=Decimal("0.0000"),
        holdings=holdings,
        data_freshness_date=max(
            (holding.latest_price_date for holding in holdings if holding.latest_price_date is not None),
            default=None,
        ),
        data_source=next((holding.data_source for holding in holdings if holding.data_source), None),
    )


def get_portfolio_exposure(db: Session, user: User, portfolio_id: str) -> PortfolioExposureResponse:
    summary = get_portfolio_summary(db, user, portfolio_id)
    sector_values: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    company_values: dict[tuple[str, str], Decimal] = defaultdict(lambda: Decimal("0"))
    for holding in summary.holdings:
        sector_values[holding.sector] += holding.market_value
        company_values[(holding.symbol, holding.name)] += holding.market_value

    def weight(value: Decimal) -> Decimal:
        return percent((value / summary.total_value) * Decimal("100")) if summary.total_value else Decimal("0")

    return PortfolioExposureResponse(
        total_value=summary.total_value,
        by_sector=[
            SectorExposureResponse(sector=sector, market_value=money(value), weight_percent=weight(value))
            for sector, value in sorted(sector_values.items(), key=lambda item: item[1], reverse=True)
        ],
        by_company=[
            CompanyExposureResponse(
                symbol=symbol, name=name, market_value=money(value), weight_percent=weight(value)
            )
            for (symbol, name), value in sorted(company_values.items(), key=lambda item: item[1], reverse=True)
        ],
    )


def get_portfolio_performance(
    db: Session, user: User, portfolio_id: str, limit: int = 90
) -> list[PortfolioPerformancePoint]:
    portfolio = get_portfolio_or_404(db, user, portfolio_id)
    holdings = db.scalars(select(PortfolioHolding).where(PortfolioHolding.portfolio_id == portfolio.id)).all()
    if not holdings:
        return []

    dates = db.scalars(
        select(MarketPrice.trade_date).distinct().order_by(MarketPrice.trade_date.desc()).limit(limit)
    ).all()
    points: list[PortfolioPerformancePoint] = []
    previous_total: Decimal | None = None
    for value_date in reversed(dates):
        total = Decimal("0")
        for holding in holdings:
            price = price_for_symbol_on_or_before(db, holding.symbol, value_date)
            if price:
                total += holding.quantity * price.close
        total = money(total)
        day_change = money(total - previous_total) if previous_total is not None else Decimal("0.0000")
        points.append(
            PortfolioPerformancePoint(
                value_date=value_date,
                total_value=total,
                day_change=day_change,
                day_change_percent=percent((day_change / previous_total) * Decimal("100"))
                if previous_total
                else None,
            )
        )
        previous_total = total
    return points


def get_portfolio_risk_flags(db: Session, user: User, portfolio_id: str) -> PortfolioRiskFlagsResponse:
    summary = get_portfolio_summary(db, user, portfolio_id)
    exposure = get_portfolio_exposure(db, user, portfolio_id)
    flags: list[PortfolioRiskFlag] = []

    for company in exposure.by_company:
        if company.weight_percent >= Decimal("40"):
            flags.append(
                PortfolioRiskFlag(
                    severity="high",
                    code="company_concentration",
                    message=f"{company.symbol} is {company.weight_percent}% of portfolio value.",
                    value=company.weight_percent,
                )
            )

    for sector in exposure.by_sector:
        if sector.weight_percent >= Decimal("50"):
            flags.append(
                PortfolioRiskFlag(
                    severity="medium",
                    code="sector_concentration",
                    message=f"{sector.sector} exposure is {sector.weight_percent}% of portfolio value.",
                    value=sector.weight_percent,
                )
            )

    missing_prices = [holding.symbol for holding in summary.holdings if holding.latest_price is None]
    if missing_prices:
        flags.append(
            PortfolioRiskFlag(
                severity="medium",
                code="missing_market_prices",
                message=f"Missing latest market prices for: {', '.join(missing_prices)}.",
            )
        )

    if not summary.holdings:
        flags.append(
            PortfolioRiskFlag(
                severity="info",
                code="empty_portfolio",
                message="Add holdings to calculate exposure and PnL.",
            )
        )

    return PortfolioRiskFlagsResponse(flags=flags)
