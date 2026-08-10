from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models.market import Company, MarketPrice
from app.models.portfolio import Portfolio, PortfolioHolding, PortfolioTransaction
from app.models.workstation import Instrument, PortfolioCashAccount


ZERO = Decimal("0")
POSITION_TYPES = {"buy", "sell", "opening_balance", "manual_adjustment", "corporate_action"}
CASH_TYPES = {"buy", "sell", "dividend", "deposit", "withdrawal", "fee", "tax", "opening_balance"}


@dataclass
class PositionState:
    instrument_id: str
    company_id: str
    symbol: str
    quantity: Decimal = ZERO
    average_cost: Decimal = ZERO


def instrument_for_symbol(db: Session, symbol: str) -> Instrument:
    instrument = db.scalar(select(Instrument).where(func.upper(Instrument.symbol) == symbol.upper()))
    if instrument is None:
        company = db.scalar(select(Company).where(func.upper(Company.symbol) == symbol.upper()))
        if company is None:
            raise HTTPException(status_code=404, detail="Instrument not found")
        instrument = Instrument(
            company_id=company.id,
            symbol=company.symbol,
            name=company.name,
            instrument_type="equity",
            currency="PKR",
            country="PK",
            sector=company.sector,
        )
        db.add(instrument)
        db.flush()
    return instrument


def baseline_date(db: Session, symbol: str) -> date:
    return db.scalar(select(func.max(MarketPrice.trade_date)).where(func.upper(MarketPrice.symbol) == symbol.upper())) or date.today()


def ensure_cash_account(db: Session, portfolio: Portfolio, currency: str | None = None) -> PortfolioCashAccount:
    normalized = (currency or portfolio.base_currency).upper()
    account = db.scalar(
        select(PortfolioCashAccount).where(
            PortfolioCashAccount.portfolio_id == portfolio.id,
            PortfolioCashAccount.currency == normalized,
            PortfolioCashAccount.name == "Primary",
        )
    )
    if account is None:
        account = PortfolioCashAccount(portfolio_id=portfolio.id, currency=normalized, name="Primary")
        db.add(account)
        db.flush()
    return account


def _transactions(db: Session, portfolio_id: str, as_of: date | None = None) -> list[PortfolioTransaction]:
    statement = select(PortfolioTransaction).where(PortfolioTransaction.portfolio_id == portfolio_id)
    if as_of is not None:
        statement = statement.where(PortfolioTransaction.transaction_date <= as_of)
    return list(db.scalars(statement.order_by(PortfolioTransaction.transaction_date, PortfolioTransaction.created_at, PortfolioTransaction.id)))


def replay_positions(db: Session, portfolio_id: str, as_of: date | None = None) -> dict[str, PositionState]:
    states: dict[str, PositionState] = {}
    reversed_ids = {row.reversal_of_id for row in _transactions(db, portfolio_id, as_of) if row.reversal_of_id}
    for row in _transactions(db, portfolio_id, as_of):
        if row.id in reversed_ids or row.reversal_of_id or row.transaction_type not in POSITION_TYPES:
            continue
        if not row.instrument_id or not row.company_id or not row.quantity:
            continue
        state = states.setdefault(row.symbol, PositionState(row.instrument_id, row.company_id, row.symbol))
        quantity = Decimal(row.quantity)
        price = Decimal(row.price or ZERO)
        if row.transaction_type in {"sell"}:
            state.quantity -= quantity
        elif row.transaction_type == "corporate_action":
            state.quantity *= quantity
        else:
            new_quantity = state.quantity + quantity
            if row.transaction_type == "manual_adjustment" and price > 0:
                state.average_cost = price
            elif quantity > 0 and price >= 0 and new_quantity > 0:
                state.average_cost = ((state.quantity * state.average_cost) + (quantity * price)) / new_quantity
            state.quantity = new_quantity
        if state.quantity < 0:
            raise HTTPException(status_code=422, detail=f"Transaction ledger produces a negative {row.symbol} position")
    return {symbol: state for symbol, state in states.items() if state.quantity > 0}


def cash_balance(db: Session, portfolio_id: str, currency: str = "PKR", as_of: date | None = None) -> Decimal:
    balance = ZERO
    rows = _transactions(db, portfolio_id, as_of)
    reversed_ids = {row.reversal_of_id for row in rows if row.reversal_of_id}
    for row in rows:
        if row.id in reversed_ids or row.reversal_of_id or row.currency.upper() != currency.upper() or row.transaction_type not in CASH_TYPES:
            continue
        amount = Decimal(row.amount or ZERO)
        fees = Decimal(row.fees or ZERO)
        taxes = Decimal(row.taxes or ZERO)
        if row.transaction_type in {"deposit", "dividend"}:
            balance += amount - fees - taxes
        elif row.transaction_type == "sell":
            balance += amount - fees - taxes
        elif row.transaction_type in {"buy", "withdrawal"}:
            balance -= amount + fees + taxes
        elif row.transaction_type in {"fee", "tax"}:
            balance -= abs(amount)
        elif row.transaction_type == "opening_balance" and row.symbol == "CASH":
            balance += amount
    return balance


def rebuild_holding_projection(db: Session, portfolio: Portfolio) -> list[PortfolioHolding]:
    states = replay_positions(db, portfolio.id)
    existing = {row.symbol: row for row in db.scalars(select(PortfolioHolding).where(PortfolioHolding.portfolio_id == portfolio.id))}
    for symbol, state in states.items():
        row = existing.pop(symbol, None)
        if row is None:
            row = PortfolioHolding(portfolio_id=portfolio.id, company_id=state.company_id, instrument_id=state.instrument_id, symbol=symbol, quantity=state.quantity, average_cost=state.average_cost)
        else:
            row.company_id = state.company_id
            row.instrument_id = state.instrument_id
            row.quantity = state.quantity
            row.average_cost = state.average_cost
        db.add(row)
    for obsolete in existing.values():
        db.delete(obsolete)
    db.flush()
    return list(db.scalars(select(PortfolioHolding).where(PortfolioHolding.portfolio_id == portfolio.id).order_by(PortfolioHolding.symbol)))


def record_holding_adjustment(
    db: Session,
    portfolio: Portfolio,
    *,
    symbol: str,
    desired_quantity: Decimal,
    average_cost: Decimal,
    notes: str,
) -> PortfolioTransaction:
    instrument = instrument_for_symbol(db, symbol)
    company_id = instrument.company_id
    if company_id is None:
        raise HTTPException(status_code=422, detail="Only equity instruments can be entered as legacy holdings")
    current = replay_positions(db, portfolio.id).get(instrument.symbol)
    current_quantity = current.quantity if current else ZERO
    delta = desired_quantity - current_quantity
    if delta == 0 and current and current.average_cost == average_cost:
        raise HTTPException(status_code=409, detail="Holding already has the requested quantity and cost")
    transaction = PortfolioTransaction(
        portfolio_id=portfolio.id,
        company_id=company_id,
        instrument_id=instrument.id,
        symbol=instrument.symbol,
        transaction_type="opening_balance" if current is None else "manual_adjustment",
        quantity=delta,
        price=average_cost,
        amount=ZERO,
        transaction_date=baseline_date(db, instrument.symbol),
        source="holding_adjustment",
        currency=portfolio.base_currency,
        notes=notes,
    )
    db.add(transaction)
    db.flush()
    portfolio.history_start = portfolio.history_start or transaction.transaction_date
    portfolio.history_complete = False
    rebuild_holding_projection(db, portfolio)
    return transaction


def reverse_transaction(db: Session, row: PortfolioTransaction, notes: str = "Reversal") -> PortfolioTransaction:
    if db.scalar(select(PortfolioTransaction).where(PortfolioTransaction.reversal_of_id == row.id)):
        raise HTTPException(status_code=409, detail="Transaction is already reversed")
    reversal = PortfolioTransaction(
        portfolio_id=row.portfolio_id,
        company_id=row.company_id,
        instrument_id=row.instrument_id,
        symbol=row.symbol,
        transaction_type=row.transaction_type,
        quantity=row.quantity,
        price=row.price,
        amount=row.amount,
        transaction_date=date.today(),
        notes=notes,
        source="reversal",
        currency=row.currency,
        fees=row.fees,
        taxes=row.taxes,
        reversal_of_id=row.id,
    )
    db.add(reversal)
    db.flush()
    portfolio = db.get(Portfolio, row.portfolio_id)
    if portfolio:
        rebuild_holding_projection(db, portfolio)
    return reversal
