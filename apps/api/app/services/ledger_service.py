from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models.market import Company
from app.models.portfolio import Portfolio, PortfolioHolding, PortfolioTransaction
from app.models.workstation import (
    CorporateAction,
    Instrument,
    PortfolioCashAccount,
    PortfolioCashSnapshot,
    PortfolioPositionSnapshot,
)
from app.services.canonical_market_service import latest_price


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
    observed = latest_price(db, symbol)
    return observed.trade_date if observed else date.today()


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
    return replay_positions_from_transactions(_transactions(db, portfolio_id, as_of))


def replay_positions_from_transactions(rows: list[PortfolioTransaction]) -> dict[str, PositionState]:
    states: dict[str, PositionState] = {}
    reversed_ids = {row.reversal_of_id for row in rows if row.reversal_of_id}
    for row in rows:
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
            # ``quantity`` is the split/consolidation multiplier.  Economic cost
            # basis is unchanged, so per-unit cost moves inversely with quantity.
            state.quantity *= quantity
            if quantity > 0:
                state.average_cost /= quantity
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
    return cash_balance_from_transactions(_transactions(db, portfolio_id, as_of), currency, as_of)


def cash_balance_from_transactions(
    rows: list[PortfolioTransaction], currency: str = "PKR", as_of: date | None = None
) -> Decimal:
    balance = ZERO
    reversed_ids = {row.reversal_of_id for row in rows if row.reversal_of_id}
    for row in rows:
        if row.id in reversed_ids or row.reversal_of_id or row.currency.upper() != currency.upper() or row.transaction_type not in CASH_TYPES:
            continue
        effective_cash_date = row.settlement_date if row.transaction_type in {"buy", "sell"} and row.settlement_date else row.transaction_date
        if as_of is not None and effective_cash_date > as_of:
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


def external_flow(db: Session, portfolio_id: str, start_exclusive: date | None, end_inclusive: date) -> Decimal:
    """Return signed external capital added during a valuation period.

    Deposits and transferred-in opening/manual positions are positive. Withdrawals
    and transferred-out manual positions are negative. Trades, income, expenses,
    and corporate actions are portfolio activity rather than external capital.
    """
    rows = _transactions(db, portfolio_id, end_inclusive)
    return external_flow_from_transactions(rows, start_exclusive, end_inclusive)


def external_flow_from_transactions(
    rows: list[PortfolioTransaction], start_exclusive: date | None, end_inclusive: date
) -> Decimal:
    """Calculate external flow from already-loaded ledger rows."""
    rows = [row for row in rows if row.transaction_date <= end_inclusive]
    reversed_ids = {row.reversal_of_id for row in rows if row.reversal_of_id}
    flow = ZERO
    for row in rows:
        if row.id in reversed_ids or row.reversal_of_id:
            continue
        if start_exclusive is not None and row.transaction_date <= start_exclusive:
            continue
        amount = Decimal(row.amount or ZERO)
        if row.transaction_type == "deposit":
            flow += amount
        elif row.transaction_type == "withdrawal":
            flow -= amount
        elif row.transaction_type == "opening_balance":
            flow += amount if row.symbol == "CASH" else Decimal(row.quantity or ZERO) * Decimal(row.price or ZERO)
        elif row.transaction_type == "manual_adjustment":
            flow += Decimal(row.quantity or ZERO) * Decimal(row.price or ZERO)
    return flow


def net_external_contributions(db: Session, portfolio_id: str, as_of: date | None = None) -> Decimal:
    return external_flow(db, portfolio_id, None, as_of or date.today())


def generate_portfolio_snapshot(
    db: Session,
    portfolio: Portfolio,
    snapshot_date: date,
    source_transaction_id: str | None = None,
) -> None:
    """Idempotently materialize ledger-derived position and cash state for a date."""
    positions = replay_positions(db, portfolio.id, snapshot_date)
    existing_positions = {
        row.instrument_id: row
        for row in db.scalars(
            select(PortfolioPositionSnapshot).where(
                PortfolioPositionSnapshot.portfolio_id == portfolio.id,
                PortfolioPositionSnapshot.snapshot_date == snapshot_date,
            )
        )
    }
    for state in positions.values():
        row = existing_positions.pop(state.instrument_id, None)
        if row is None:
            row = PortfolioPositionSnapshot(
                portfolio_id=portfolio.id,
                instrument_id=state.instrument_id,
                snapshot_date=snapshot_date,
                quantity=state.quantity,
                average_cost=state.average_cost,
            )
        else:
            row.quantity = state.quantity
            row.average_cost = state.average_cost
        row.source_transaction_id = source_transaction_id
        db.add(row)
    for obsolete in existing_positions.values():
        db.delete(obsolete)

    accounts = list(
        db.scalars(
            select(PortfolioCashAccount).where(PortfolioCashAccount.portfolio_id == portfolio.id)
        )
    )
    for account in accounts:
        row = db.scalar(
            select(PortfolioCashSnapshot).where(
                PortfolioCashSnapshot.cash_account_id == account.id,
                PortfolioCashSnapshot.snapshot_date == snapshot_date,
            )
        )
        if row is None:
            row = PortfolioCashSnapshot(cash_account_id=account.id, snapshot_date=snapshot_date, balance=ZERO)
        row.balance = cash_balance(db, portfolio.id, account.currency, snapshot_date)
        row.source_transaction_id = source_transaction_id
        db.add(row)
    db.flush()


def generate_daily_snapshots(db: Session, snapshot_date: date | None = None) -> int:
    target = snapshot_date or date.today()
    portfolios = list(db.scalars(select(Portfolio).where(Portfolio.archived_at.is_(None))))
    for portfolio in portfolios:
        ensure_cash_account(db, portfolio)
        generate_portfolio_snapshot(db, portfolio, target)
    db.commit()
    return len(portfolios)


def apply_recorded_corporate_actions(db: Session, through_date: date | None = None) -> dict[str, int]:
    """Apply only structured, recorded actions to entitled ledger positions.

    Supported contracts are explicit: split/consolidation requires
    ``split_multiplier`` and cash dividend requires ``cash_per_share``. Unknown
    action payloads are counted as unsupported rather than guessed.
    """
    import json

    cutoff = through_date or date.today()
    actions = list(db.scalars(select(CorporateAction).where(CorporateAction.effective_date <= cutoff).order_by(CorporateAction.effective_date)))
    applied = skipped = unsupported = 0
    affected: dict[str, tuple[Portfolio, date, str]] = {}
    portfolios = list(db.scalars(select(Portfolio).where(Portfolio.archived_at.is_(None))))
    for action in actions:
        instrument = db.get(Instrument, action.instrument_id)
        if instrument is None or instrument.company_id is None:
            unsupported += 1
            continue
        details = json.loads(action.details_json)
        action_type = action.action_type.lower()
        transaction_date = action.payment_date if action_type in {"cash_dividend", "dividend"} and action.payment_date else action.effective_date
        for portfolio in portfolios:
            external_id = f"corporate_action:{action.id}"
            if db.scalar(select(PortfolioTransaction.id).where(PortfolioTransaction.portfolio_id == portfolio.id, PortfolioTransaction.external_id == external_id)):
                skipped += 1
                continue
            entitlement_date = action.ex_date or action.effective_date
            state = replay_positions(db, portfolio.id, entitlement_date - timedelta(days=1)).get(instrument.symbol)
            if state is None or state.quantity <= 0:
                continue
            if action_type in {"split", "stock_split", "consolidation"} and details.get("split_multiplier"):
                multiplier = Decimal(str(details["split_multiplier"]))
                if multiplier <= 0:
                    unsupported += 1
                    continue
                transaction = PortfolioTransaction(portfolio_id=portfolio.id, company_id=instrument.company_id, instrument_id=instrument.id, symbol=instrument.symbol, transaction_type="corporate_action", quantity=multiplier, price=ZERO, amount=ZERO, transaction_date=transaction_date, source="recorded_corporate_action", currency=portfolio.base_currency, external_id=external_id, notes=f"Applied corporate action {action.id}")
            elif action_type in {"cash_dividend", "dividend"} and details.get("cash_per_share") is not None:
                cash_per_share = Decimal(str(details["cash_per_share"]))
                if cash_per_share < 0:
                    unsupported += 1
                    continue
                transaction = PortfolioTransaction(portfolio_id=portfolio.id, company_id=instrument.company_id, instrument_id=instrument.id, symbol=instrument.symbol, transaction_type="dividend", quantity=state.quantity, price=cash_per_share, amount=state.quantity * cash_per_share, transaction_date=transaction_date, source="recorded_corporate_action", currency=portfolio.base_currency, external_id=external_id, notes=f"Applied corporate action {action.id}")
            else:
                unsupported += 1
                continue
            db.add(transaction); db.flush(); applied += 1
            affected[portfolio.id] = (portfolio, transaction_date, transaction.id)
    for portfolio, transaction_date, transaction_id in affected.values():
        rebuild_holding_projection(db, portfolio)
        generate_portfolio_snapshot(db, portfolio, transaction_date, transaction_id)
    db.commit()
    return {"applied": applied, "already_applied": skipped, "unsupported": unsupported}


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
    generate_portfolio_snapshot(db, portfolio, transaction.transaction_date, transaction.id)
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
        generate_portfolio_snapshot(db, portfolio, reversal.transaction_date, reversal.id)
    return reversal
