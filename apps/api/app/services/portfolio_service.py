from collections import defaultdict
from datetime import UTC, date, datetime
from decimal import Decimal, ROUND_HALF_UP
import json

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.market import Company, MarketPrice
from app.models.portfolio import Portfolio, PortfolioHolding, PortfolioTransaction
from app.models.user import User
from app.models.workstation import AllocationItem, AllocationSet, PortfolioIPS, PortfolioIPSVersion
from app.services.ledger_service import (
    cash_balance,
    ensure_cash_account,
    instrument_for_symbol,
    rebuild_holding_projection,
    record_holding_adjustment,
    replay_positions,
    reverse_transaction,
)
from app.services.portfolio_providers import describe_portfolio_source, get_portfolio_provider
from app.schemas.portfolio import (
    AllocationItemResponse,
    AllocationSetCreate,
    AllocationSetResponse,
    CashBalanceResponse,
    CompanyExposureResponse,
    HoldingCreate,
    HoldingResponse,
    HoldingSummary,
    HoldingUpdate,
    PortfolioCreate,
    PortfolioDuplicateRequest,
    PortfolioExposureResponse,
    PortfolioPerformancePoint,
    PortfolioResponse,
    PortfolioRiskFlag,
    PortfolioRiskFlagsResponse,
    PortfolioSummaryResponse,
    PortfolioUpdate,
    PositionResponse,
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
        description=portfolio.description,
        goal_summary=portfolio.goal_summary,
        is_default=portfolio.is_default,
        archived_at=portfolio.archived_at,
        history_start=portfolio.history_start,
        history_complete=portfolio.history_complete,
        selected_ips_version_id=portfolio.selected_ips_version_id,
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
        currency=transaction.currency,
        fees=transaction.fees,
        taxes=transaction.taxes,
        settlement_date=transaction.settlement_date,
        external_id=transaction.external_id,
        reversal_of_id=transaction.reversal_of_id,
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
        description=payload.description,
        goal_summary=payload.goal_summary,
        is_default=(db.scalar(select(func.count(Portfolio.id)).where(Portfolio.user_id == user.id)) or 0) == 0,
    )
    db.add(portfolio)
    db.flush()
    ensure_cash_account(db, portfolio)
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
    for field in ("description", "goal_summary"):
        if field in data:
            setattr(portfolio, field, data[field])
    db.add(portfolio)
    db.commit()
    db.refresh(portfolio)
    return serialize_portfolio(portfolio)


def delete_portfolio(db: Session, user: User, portfolio_id: str, *, confirmed: bool = False) -> None:
    portfolio = get_portfolio_or_404(db, user, portfolio_id)
    if not confirmed:
        raise HTTPException(status_code=409, detail="Permanent deletion requires confirm=true")
    db.delete(portfolio)
    db.commit()


def archive_portfolio(db: Session, user: User, portfolio_id: str) -> PortfolioResponse:
    portfolio = get_portfolio_or_404(db, user, portfolio_id)
    portfolio.archived_at = datetime.now(UTC)
    portfolio.is_default = False
    db.commit(); db.refresh(portfolio)
    return serialize_portfolio(portfolio)


def restore_portfolio(db: Session, user: User, portfolio_id: str) -> PortfolioResponse:
    portfolio = get_portfolio_or_404(db, user, portfolio_id)
    portfolio.archived_at = None
    db.commit(); db.refresh(portfolio)
    return serialize_portfolio(portfolio)


def select_default_portfolio(db: Session, user: User, portfolio_id: str) -> PortfolioResponse:
    portfolio = get_portfolio_or_404(db, user, portfolio_id)
    if portfolio.archived_at:
        raise HTTPException(status_code=409, detail="Archived portfolios cannot be selected as default")
    for row in db.scalars(select(Portfolio).where(Portfolio.user_id == user.id)):
        row.is_default = row.id == portfolio.id
    db.commit(); db.refresh(portfolio)
    return serialize_portfolio(portfolio)


def duplicate_portfolio(db: Session, user: User, portfolio_id: str, payload: PortfolioDuplicateRequest) -> PortfolioResponse:
    source = get_portfolio_or_404(db, user, portfolio_id)
    duplicate = Portfolio(user_id=user.id, name=payload.name, base_currency=source.base_currency, source_mode="manual", provider_name="ManualPortfolioProvider", description=source.description, goal_summary=source.goal_summary)
    db.add(duplicate); db.flush(); ensure_cash_account(db, duplicate)
    latest_ips = db.scalar(select(PortfolioIPSVersion).where(PortfolioIPSVersion.portfolio_id == source.id, PortfolioIPSVersion.status == "confirmed").order_by(PortfolioIPSVersion.version.desc()))
    if latest_ips:
        copied = PortfolioIPSVersion(portfolio_id=duplicate.id, version=1, status="confirmed", constraints_json=latest_ips.constraints_json, required_return=latest_ips.required_return, confirmed_at=datetime.now(UTC))
        db.add(copied); db.flush()
        db.add(PortfolioIPS(portfolio_id=duplicate.id, current_version_id=copied.id))
        duplicate.selected_ips_version_id = copied.id
    for allocation in db.scalars(select(AllocationSet).where(AllocationSet.portfolio_id == source.id, AllocationSet.kind.in_(["sandbox", "target"]))):
        copied_set = AllocationSet(portfolio_id=duplicate.id, kind=allocation.kind, version=allocation.version, status=allocation.status, assumptions_json=allocation.assumptions_json, base_value=allocation.base_value, created_by_user_id=user.id)
        db.add(copied_set); db.flush()
        for item in db.scalars(select(AllocationItem).where(AllocationItem.allocation_set_id == allocation.id)):
            db.add(AllocationItem(allocation_set_id=copied_set.id, symbol=item.symbol, instrument_id=item.instrument_id, is_cash=item.is_cash, target_weight=item.target_weight, target_amount=item.target_amount, target_quantity=item.target_quantity, locked=item.locked))
    if payload.include_positions:
        for holding in db.scalars(select(PortfolioHolding).where(PortfolioHolding.portfolio_id == source.id)):
            record_holding_adjustment(db, duplicate, symbol=holding.symbol, desired_quantity=holding.quantity, average_cost=holding.average_cost, notes=f"Opening balance duplicated from portfolio {source.id}")
    db.commit(); db.refresh(duplicate)
    return serialize_portfolio(duplicate)


def add_holding(db: Session, user: User, portfolio_id: str, payload: HoldingCreate) -> HoldingResponse:
    portfolio = get_portfolio_or_404(db, user, portfolio_id)
    transaction = record_holding_adjustment(db, portfolio, symbol=payload.symbol, desired_quantity=payload.quantity, average_cost=payload.average_cost, notes="Holding opening balance")
    db.commit()
    holding = db.scalar(select(PortfolioHolding).where(PortfolioHolding.portfolio_id == portfolio.id, PortfolioHolding.instrument_id == transaction.instrument_id))
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
    portfolio = get_portfolio_or_404(db, user, holding.portfolio_id)
    record_holding_adjustment(db, portfolio, symbol=holding.symbol, desired_quantity=payload.quantity or holding.quantity, average_cost=payload.average_cost if payload.average_cost is not None else holding.average_cost, notes="Auditable holding adjustment")
    db.commit()
    updated = db.scalar(select(PortfolioHolding).where(PortfolioHolding.portfolio_id == portfolio.id, PortfolioHolding.symbol == holding.symbol))
    return serialize_holding(updated)


def delete_holding(db: Session, user: User, holding_id: str) -> None:
    holding = get_holding_or_404(db, user, holding_id)
    portfolio = get_portfolio_or_404(db, user, holding.portfolio_id)
    record_holding_adjustment(db, portfolio, symbol=holding.symbol, desired_quantity=Decimal("0"), average_cost=holding.average_cost, notes="Auditable holding removal")
    db.commit()


def add_transaction(
    db: Session, user: User, portfolio_id: str, payload: TransactionCreate
) -> TransactionResponse:
    portfolio = get_portfolio_or_404(db, user, portfolio_id)
    instrument = None if payload.symbol.upper() == "CASH" else instrument_for_symbol(db, payload.symbol)
    company = db.get(Company, instrument.company_id) if instrument and instrument.company_id else None
    if payload.transaction_type in {"buy", "sell", "dividend", "corporate_action"} and instrument is None:
        raise HTTPException(status_code=422, detail="This transaction type requires an instrument")
    transaction = PortfolioTransaction(
        portfolio_id=portfolio.id,
        company_id=company.id if company else None,
        instrument_id=instrument.id if instrument else None,
        symbol=company.symbol if company else payload.symbol.upper(),
        transaction_type=payload.transaction_type,
        quantity=payload.quantity,
        price=payload.price,
        amount=payload.amount,
        transaction_date=payload.transaction_date,
        notes=payload.notes,
        source=payload.source,
        currency=payload.currency.upper(),
        fees=payload.fees,
        taxes=payload.taxes,
        settlement_date=payload.settlement_date,
        external_id=payload.external_id,
    )
    db.add(transaction)
    ensure_cash_account(db, portfolio, payload.currency)
    db.flush()
    rebuild_holding_projection(db, portfolio)
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
    immutable = set(data) - {"notes", "external_id", "settlement_date"}
    if immutable:
        raise HTTPException(status_code=409, detail="Financial transaction fields are immutable; reverse and replace the transaction")
    for key, value in data.items():
        setattr(transaction, key, value)
    db.add(transaction)
    db.commit()
    db.refresh(transaction)
    return serialize_transaction(transaction)


def delete_transaction(db: Session, user: User, transaction_id: str) -> None:
    transaction = get_transaction_or_404(db, user, transaction_id)
    reverse_transaction(db, transaction, notes="Reversed by user request")
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
    cash = cash_balance(db, portfolio.id, portfolio.base_currency)
    total_value = money(sum((holding.market_value for holding in holdings), Decimal("0")) + cash)
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
        cash_balance=money(cash),
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
    if not db.scalar(select(func.count(PortfolioTransaction.id)).where(PortfolioTransaction.portfolio_id == portfolio.id)):
        return []

    dates = db.scalars(
        select(MarketPrice.trade_date).distinct().order_by(MarketPrice.trade_date.desc()).limit(limit)
    ).all()
    points: list[PortfolioPerformancePoint] = []
    previous_total: Decimal | None = None
    for value_date in reversed(dates):
        total = cash_balance(db, portfolio.id, portfolio.base_currency, value_date)
        for position in replay_positions(db, portfolio.id, value_date).values():
            price = price_for_symbol_on_or_before(db, position.symbol, value_date)
            if price:
                total += position.quantity * price.close
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


def get_positions(db: Session, user: User, portfolio_id: str) -> list[PositionResponse]:
    portfolio = get_portfolio_or_404(db, user, portfolio_id)
    return [PositionResponse(instrument_id=row.instrument_id, symbol=row.symbol, quantity=row.quantity, average_cost=row.average_cost) for row in replay_positions(db, portfolio.id).values()]


def get_cash(db: Session, user: User, portfolio_id: str) -> CashBalanceResponse:
    portfolio = get_portfolio_or_404(db, user, portfolio_id)
    ensure_cash_account(db, portfolio)
    return CashBalanceResponse(currency=portfolio.base_currency, balance=money(cash_balance(db, portfolio.id, portfolio.base_currency)))


def _serialize_allocation(db: Session, row: AllocationSet) -> AllocationSetResponse:
    items = list(db.scalars(select(AllocationItem).where(AllocationItem.allocation_set_id == row.id).order_by(AllocationItem.symbol)))
    return AllocationSetResponse(
        id=row.id, portfolio_id=row.portfolio_id, kind=row.kind, version=row.version,
        status=row.status, base_value=row.base_value, assumptions=json.loads(row.assumptions_json),
        items=[AllocationItemResponse(id=item.id, symbol=item.symbol, instrument_id=item.instrument_id, target_weight=item.target_weight, target_amount=item.target_amount, target_quantity=item.target_quantity, locked=item.locked, is_cash=item.is_cash) for item in items],
        created_at=row.created_at,
    )


def create_allocation_set(db: Session, user: User, portfolio_id: str, payload: AllocationSetCreate) -> AllocationSetResponse:
    portfolio = get_portfolio_or_404(db, user, portfolio_id)
    if abs(sum((item.target_weight for item in payload.items), Decimal("0")) - Decimal("1")) > Decimal("0.000001"):
        raise HTTPException(status_code=422, detail="Allocation weights must sum to one")
    version = (db.scalar(select(func.max(AllocationSet.version)).where(AllocationSet.portfolio_id == portfolio.id, AllocationSet.kind == payload.kind)) or 0) + 1
    row = AllocationSet(portfolio_id=portfolio.id, kind=payload.kind, version=version, status="draft" if payload.kind == "sandbox" else "active", assumptions_json=json.dumps(payload.assumptions, sort_keys=True), base_value=payload.base_value, created_by_user_id=user.id)
    db.add(row); db.flush()
    for item in payload.items:
        instrument = None if item.is_cash else instrument_for_symbol(db, item.symbol)
        amount = payload.base_value * item.target_weight if payload.base_value is not None else None
        latest = latest_price_for_symbol(db, item.symbol) if instrument else None
        quantity = amount / latest.close if amount is not None and latest and latest.close else None
        db.add(AllocationItem(allocation_set_id=row.id, symbol="CASH" if item.is_cash else instrument.symbol, instrument_id=instrument.id if instrument else None, is_cash=item.is_cash, target_weight=item.target_weight, target_amount=amount, target_quantity=quantity, locked=item.locked))
    db.commit(); db.refresh(row)
    return _serialize_allocation(db, row)


def list_allocation_sets(db: Session, user: User, portfolio_id: str) -> list[AllocationSetResponse]:
    portfolio = get_portfolio_or_404(db, user, portfolio_id)
    return [_serialize_allocation(db, row) for row in db.scalars(select(AllocationSet).where(AllocationSet.portfolio_id == portfolio.id).order_by(AllocationSet.created_at.desc()))]


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
