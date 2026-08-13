from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.market import Company
from app.models.portfolio import Portfolio, PortfolioHolding, PortfolioTransaction
from app.models.user import User


def get_portfolio_or_404(db: Session, user: User, portfolio_id: str) -> Portfolio:
    portfolio = db.scalar(select(Portfolio).where(Portfolio.id == portfolio_id, Portfolio.user_id == user.id))
    if not portfolio:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Portfolio not found")
    return portfolio


def get_holding_or_404(db: Session, user: User, holding_id: str) -> PortfolioHolding:
    holding = db.scalar(select(PortfolioHolding).join(Portfolio, Portfolio.id == PortfolioHolding.portfolio_id).where(PortfolioHolding.id == holding_id, Portfolio.user_id == user.id))
    if not holding:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Holding not found")
    return holding


def get_transaction_or_404(db: Session, user: User, transaction_id: str) -> PortfolioTransaction:
    transaction = db.scalar(select(PortfolioTransaction).join(Portfolio, Portfolio.id == PortfolioTransaction.portfolio_id).where(PortfolioTransaction.id == transaction_id, Portfolio.user_id == user.id))
    if not transaction:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")
    return transaction


def get_company_by_symbol_or_404(db: Session, symbol: str) -> Company:
    company = db.scalar(select(Company).where(func.upper(Company.symbol) == symbol.upper(), Company.is_active.is_(True)))
    if not company:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")
    return company
