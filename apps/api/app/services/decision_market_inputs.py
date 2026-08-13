from datetime import date

import numpy as np
from sqlalchemy.orm import Session

from app.domain.quant import covariance_matrix, estimate_expected_returns, return_matrix
from app.models.user import User
from app.services.canonical_market_service import price_series
from app.services.portfolio_service import get_portfolio_or_404, get_portfolio_summary
from app.services.workstation_service import _aligned_prices, _aligned_symbol_prices, _benchmark_symbol, _effective_risk_free_rate, _selected_ips_constraints


def market_inputs(db: Session, user: User, portfolio_id: str, extra_symbols: list[str] | None = None, risk_free_loader=None):
    portfolio = get_portfolio_or_404(db, user, portfolio_id)
    if extra_symbols:
        summary = get_portfolio_summary(db, user, portfolio.id)
        universe = [row.symbol for row in summary.holdings] + [symbol.upper() for symbol in extra_symbols if symbol.upper() != "CASH"]
        symbols, days, prices = _aligned_symbol_prices(db, universe, None, None)
    else:
        symbols, days, prices = _aligned_prices(db, portfolio.id, None, None)
    returns = return_matrix(prices); covariance = covariance_matrix(returns, 0.20); expected = estimate_expected_returns("historical_shrunk", returns, shrinkage=0.50)
    constraints = _selected_ips_constraints(db, portfolio); benchmark_symbol = _benchmark_symbol(db, portfolio, constraints)
    loader = risk_free_loader or _effective_risk_free_rate
    risk_free = loader(db, days[-1], str(constraints.get("risk_free_series_key")) if constraints.get("risk_free_series_key") else None)
    return portfolio, symbols, days, returns, covariance, expected, constraints, benchmark_symbol, risk_free


def benchmark_returns(db: Session, symbol: str | None, days: list[date]) -> np.ndarray | None:
    if not symbol: return None
    by_date = {row.trade_date: float(row.close) for row in price_series(db, symbol)}
    if any(day not in by_date for day in days): return None
    prices = np.asarray([by_date[day] for day in days], dtype=float)
    return prices[1:] / prices[:-1] - 1
