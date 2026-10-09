"""Read-only extras for the Scenarios tab, derived from stored scenario runs.

Everything here is computed from persisted ``ScenarioRun`` rows and stored price history.
Nothing is invented: when volatility cannot be estimated the field is ``None`` with a reason.
"""
import json

import numpy as np
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.quant import covariance_matrix, return_matrix
from app.models.user import User
from app.models.workstation import ScenarioRun
from app.services.portfolio_service import get_portfolio_or_404
from app.services.workstation_service import _aligned_prices

VOLATILITY_METHOD = (
    "Annualised volatility from the stored aligned price history of the portfolio's current holdings, "
    "applied to the run-time position weights (before) and the post-shock weights (after). "
    "It re-weights historical covariance; it does not forecast shocked volatility."
)


def _loads(value: str | None) -> dict:
    try:
        parsed = json.loads(value or "{}")
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _volatility(weights: dict[str, float], symbols: list[str], covariance: np.ndarray) -> float:
    vector = np.asarray([weights.get(symbol, 0.0) for symbol in symbols])
    return float(np.sqrt(max(vector @ covariance @ vector, 0.0)))


def volatility_change(positions: list[dict], portfolio_value: float, stressed_value: float, symbols: list[str], covariance: np.ndarray):
    """Return (before, after, reason) as annualised volatility; weights are on total capital incl. cash."""
    if not symbols or portfolio_value <= 0 or stressed_value <= 0:
        return None, None, "Portfolio value is not positive for this run."
    run_symbols = {str(row.get("symbol")) for row in positions}
    if not run_symbols.intersection(symbols):
        return None, None, "None of the run's holdings have stored price history."
    before = {str(row["symbol"]): float(row.get("value") or 0) / portfolio_value for row in positions}
    after = {str(row["symbol"]): (float(row.get("value") or 0) + float(row.get("pnl") or 0)) / stressed_value for row in positions}
    return _volatility(before, symbols, covariance), _volatility(after, symbols, covariance), None


def scenario_run_extras(db: Session, user: User, portfolio_id: str) -> dict:
    portfolio = get_portfolio_or_404(db, user, portfolio_id)
    rows = db.scalars(select(ScenarioRun).where(ScenarioRun.portfolio_id == portfolio.id).order_by(ScenarioRun.created_at.desc())).all()
    symbols: list[str] = []
    covariance: np.ndarray | None = None
    model_reason: str | None = None
    try:
        symbols, _days, prices = _aligned_prices(db, portfolio.id, None, None)
        covariance = covariance_matrix(return_matrix(prices), 0.20)
    except HTTPException as exc:
        model_reason = str(exc.detail)
    runs = []
    for row in rows:
        result = _loads(row.result_json)
        shocks = _loads(row.shocks_json)
        meta = _loads(row.assumptions_json)
        positions = [item for item in result.get("positions", []) if isinstance(item, dict)]
        before = after = None
        reason = model_reason
        if covariance is not None:
            before, after, reason = volatility_change(positions, float(result.get("portfolio_value") or 0), float(result.get("stressed_portfolio_value") or 0), symbols, covariance)
        runs.append({
            "id": row.id,
            "created_at": row.created_at,
            "scenario_type": meta.get("scenario_type"),
            "shocks": {"instruments": shocks.get("instruments", {}), "sectors": shocks.get("sectors", {}), "factors": shocks.get("factors", {})},
            "volatility_before": before,
            "volatility_after": after,
            "volatility_change": None if before is None or after is None else after - before,
            "volatility_unavailable_reason": reason if before is None else None,
        })
    return {"portfolio_id": portfolio.id, "volatility_method": VOLATILITY_METHOD, "runs": runs}
