from __future__ import annotations

import numpy as np
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.market import Company
from app.models.user import User
from app.models.workstation import Instrument
from app.services.decision_market_inputs import market_inputs
from app.services.portfolio_service import get_portfolio_or_404, get_portfolio_summary
from app.services.workstation_service import _effective_risk_free_rate

CASH_SECTOR = "Cash"


def max_drawdown(daily_returns: np.ndarray, weights: np.ndarray) -> float | None:
    """Worst peak-to-trough fall (negative decimal) of a constant-weight portfolio.

    Weights are total-capital weights over the risky symbols; the residual (cash) earns 0.
    """
    if daily_returns.size == 0 or weights.size != daily_returns.shape[1]:
        return None
    path = np.cumprod(1.0 + daily_returns @ weights)
    peaks = np.maximum.accumulate(np.concatenate([[1.0], path]))
    return float(np.min(np.concatenate([[1.0], path]) / peaks - 1.0))


def _sector_weights(weights: dict[str, float], sectors: dict[str, str]) -> dict[str, float]:
    out: dict[str, float] = {}
    for symbol, weight in weights.items():
        if weight <= 0:
            continue
        sector = CASH_SECTOR if symbol == "CASH" else sectors.get(symbol) or "Unclassified"
        out[sector] = out.get(sector, 0.0) + weight
    return out


def build_extras(db: Session, user: User, portfolio_id: str, target_weights: dict[str, float] | None) -> dict:
    portfolio = get_portfolio_or_404(db, user, portfolio_id)
    summary = get_portfolio_summary(db, user, portfolio.id)
    total = float(summary.total_value)
    current = {row.symbol: float(row.market_value) / total if total else 0.0 for row in summary.holdings}
    current["CASH"] = float(summary.cash_balance) / total if total else 0.0
    proposed = {key.upper(): float(value) for key, value in (target_weights or {}).items()}
    symbols = sorted({*current, *proposed} - {"CASH"})
    companies = {row.symbol: row for row in db.scalars(select(Company).where(Company.symbol.in_(symbols)))} if symbols else {}
    instruments = {row.symbol: row for row in db.scalars(select(Instrument).where(Instrument.symbol.in_(symbols)))} if symbols else {}
    info = []
    sectors: dict[str, str] = {}
    for symbol in symbols:
        company, instrument = companies.get(symbol), instruments.get(symbol)
        sector = (company.sector if company else None) or (instrument.sector if instrument else None)
        if sector:
            sectors[symbol] = sector
        info.append({"symbol": symbol, "name": (company.name if company else None) or (instrument.name if instrument else None),
                     "sector": sector, "official_website": company.official_website if company else None})
    drawdown = {"current": None, "proposed": None}
    note = None
    try:
        _, risky, days, returns, *_ = market_inputs(db, user, portfolio.id, [s for s in proposed if s != "CASH"] or None, _effective_risk_free_rate)
        drawdown["current"] = max_drawdown(returns, np.asarray([current.get(s, 0.0) for s in risky]))
        if proposed:
            drawdown["proposed"] = max_drawdown(returns, np.asarray([proposed.get(s, 0.0) for s in risky]))
        basis = {"start": days[0].isoformat(), "end": days[-1].isoformat(), "observations": len(days) - 1}
    except HTTPException as error:
        if error.status_code == 404:
            raise
        basis, note = None, "Aligned price history is unavailable, so drawdown cannot be computed."
    except ValueError:
        basis, note = None, "Aligned price history is unavailable, so drawdown cannot be computed."
    return {
        "portfolio_id": portfolio.id,
        "instruments": info,
        "sector_weights": {"current": _sector_weights(current, sectors), "proposed": _sector_weights(proposed, sectors) if proposed else None},
        "max_drawdown": {**drawdown, "basis": "constant total-capital weights over the aligned daily price history; cash earns 0%; not a forecast", "sample": basis, "note": note},
    }
