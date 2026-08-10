import json
from datetime import UTC, date, datetime
from decimal import Decimal

import numpy as np
from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.quant import covariance_matrix, estimate_expected_returns, optimize, return_matrix, risk_metrics
from app.models.market import MarketPrice
from app.models.portfolio import PortfolioHolding
from app.models.user import User
from app.models.workstation import (
    InvestorFinancialProfileVersion,
    MonitoringRule,
    OptimizerRun,
    PortfolioIPSVersion,
    Recommendation,
    ScenarioRun,
)
from app.schemas.workstation import IPSDraft, OptimizerRequest, ScenarioRequest, VersionDraft
from app.services.portfolio_service import get_portfolio_or_404, get_portfolio_summary


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _load(value: str) -> dict:
    return json.loads(value)


def save_profile_version(db: Session, user: User, payload: VersionDraft, confirm: bool = False):
    version = (db.scalar(select(func.max(InvestorFinancialProfileVersion.version)).where(InvestorFinancialProfileVersion.user_id == user.id)) or 0) + 1
    row = InvestorFinancialProfileVersion(
        user_id=user.id, version=version, status="confirmed" if confirm else "draft",
        profile_json=_json(payload.data), confirmed_at=datetime.now(UTC) if confirm else None,
    )
    db.add(row); db.commit(); db.refresh(row)
    return {"id": row.id, "version": row.version, "status": row.status, "data": payload.data, "confirmed_at": row.confirmed_at}


def list_profile_versions(db: Session, user: User):
    rows = db.scalars(select(InvestorFinancialProfileVersion).where(InvestorFinancialProfileVersion.user_id == user.id).order_by(InvestorFinancialProfileVersion.version.desc())).all()
    return [{"id": r.id, "version": r.version, "status": r.status, "data": _load(r.profile_json), "confirmed_at": r.confirmed_at} for r in rows]


def save_ips_version(db: Session, user: User, portfolio_id: str, payload: IPSDraft, confirm: bool = False):
    portfolio = get_portfolio_or_404(db, user, portfolio_id)
    version = (db.scalar(select(func.max(PortfolioIPSVersion.version)).where(PortfolioIPSVersion.portfolio_id == portfolio.id)) or 0) + 1
    required_return = None
    if payload.starting_capital and payload.target_value and payload.horizon_years:
        required_return = (payload.target_value / payload.starting_capital) ** (1 / payload.horizon_years) - 1
        if required_return <= -1 or not np.isfinite(required_return):
            raise HTTPException(status_code=422, detail="Goal inputs do not produce a feasible required return")
    row = PortfolioIPSVersion(
        portfolio_id=portfolio.id, version=version, status="confirmed" if confirm else "draft",
        constraints_json=_json(payload.constraints), required_return=required_return,
        confirmed_at=datetime.now(UTC) if confirm else None,
    )
    db.add(row); db.commit(); db.refresh(row)
    return {"id": row.id, "version": row.version, "status": row.status, "constraints": payload.constraints, "required_return": float(row.required_return) if row.required_return is not None else None, "confirmed_at": row.confirmed_at}


def list_ips_versions(db: Session, user: User, portfolio_id: str):
    portfolio = get_portfolio_or_404(db, user, portfolio_id)
    rows = db.scalars(select(PortfolioIPSVersion).where(PortfolioIPSVersion.portfolio_id == portfolio.id).order_by(PortfolioIPSVersion.version.desc())).all()
    return [{"id": r.id, "version": r.version, "status": r.status, "constraints": _load(r.constraints_json), "required_return": float(r.required_return) if r.required_return is not None else None, "confirmed_at": r.confirmed_at} for r in rows]


def _aligned_prices(db: Session, portfolio_id: str, start: date | None, end: date | None):
    symbols = list(db.scalars(select(PortfolioHolding.symbol).where(PortfolioHolding.portfolio_id == portfolio_id).order_by(PortfolioHolding.symbol)).all())
    if len(symbols) < 2:
        raise HTTPException(status_code=422, detail="At least two holdings are required")
    statement = select(MarketPrice).where(MarketPrice.symbol.in_(symbols))
    if start: statement = statement.where(MarketPrice.trade_date >= start)
    if end: statement = statement.where(MarketPrice.trade_date <= end)
    rows = db.scalars(statement.order_by(MarketPrice.trade_date)).all()
    by_symbol = {symbol: {} for symbol in symbols}
    for row in rows:
        by_symbol[row.symbol][row.trade_date] = float(row.close)
    aligned_dates = sorted(set.intersection(*(set(values) for values in by_symbol.values())))
    if len(aligned_dates) < 31:
        raise HTTPException(status_code=422, detail="At least 31 aligned price observations are required")
    prices = [[by_symbol[symbol][day] for day in aligned_dates] for symbol in symbols]
    return symbols, aligned_dates, prices


def portfolio_quant(db: Session, user: User, portfolio_id: str, shrinkage: float = 0.20):
    portfolio = get_portfolio_or_404(db, user, portfolio_id)
    symbols, days, prices = _aligned_prices(db, portfolio.id, None, None)
    returns = return_matrix(prices)
    covariance = covariance_matrix(returns, shrinkage)
    summary = get_portfolio_summary(db, user, portfolio_id)
    market_values = {row.symbol: float(row.market_value) for row in summary.holdings}
    total = sum(market_values.values())
    weights = np.array([market_values[s] / total for s in symbols])
    metrics = risk_metrics((returns @ weights).tolist()).to_dict()
    metrics["concentration_hhi"] = float(weights @ weights)
    metrics["variance"] = float(weights @ covariance @ weights)
    return {"data_cutoff": days[-1], "symbols": symbols, "sample_size": len(days) - 1, "annualization": 252, "covariance_shrinkage": shrinkage, "portfolio": metrics, "warnings": ["Historical analytics use current holdings because a complete pre-baseline ledger is unavailable."]}


def run_optimizer(db: Session, user: User, portfolio_id: str, payload: OptimizerRequest):
    portfolio = get_portfolio_or_404(db, user, portfolio_id)
    symbols, days, prices = _aligned_prices(db, portfolio.id, payload.start_date, payload.end_date)
    returns = return_matrix(prices)
    covariance = covariance_matrix(returns, payload.covariance_shrinkage)
    estimate = None
    if payload.expected_return_method == "capm":
        raise HTTPException(status_code=422, detail="CAPM requires an effective-dated risk-free series and aligned benchmark data; neither is available for this portfolio")
    if payload.expected_return_method:
        assumptions = [payload.expected_return_assumptions[s] for s in symbols] if payload.expected_return_method == "user_model" else None
        estimate = estimate_expected_returns(payload.expected_return_method, returns, assumptions=assumptions, shrinkage=payload.expected_return_shrinkage)
    result = optimize(
        covariance, objective=payload.objective, expected_returns=estimate.values if estimate else None,
        target_return=payload.target_return, lower_bounds=[payload.minimum_weight] * len(symbols),
        upper_bounds=[payload.maximum_weight] * len(symbols),
    )
    assumptions_data = {"covariance": "diagonal_shrinkage", "covariance_shrinkage": payload.covariance_shrinkage, "expected_returns": estimate.assumptions if estimate else None, "annualization": 252}
    result_data = result.to_dict()
    row = OptimizerRun(portfolio_id=portfolio.id, objective=payload.objective, expected_return_method=payload.expected_return_method, data_cutoff=days[-1], input_json=_json(payload.model_dump(mode="json")), result_json=_json({**result_data, "symbols": symbols}), status=result.status, diagnostics_json=_json(result.diagnostics))
    db.add(row); db.commit(); db.refresh(row)
    return {"id": row.id, "status": result.status, "objective": payload.objective, "expected_return_method": payload.expected_return_method, "data_cutoff": days[-1], "symbols": symbols, "weights": dict(zip(symbols, result.weights, strict=True)) if result.weights else {}, "expected_return": result.expected_return, "volatility": result.volatility, "diagnostics": result.diagnostics, "assumptions": assumptions_data}


def run_scenario(db: Session, user: User, portfolio_id: str, payload: ScenarioRequest):
    portfolio = get_portfolio_or_404(db, user, portfolio_id)
    summary = get_portfolio_summary(db, user, portfolio_id)
    positions, pnl = [], 0.0
    for holding in summary.holdings:
        value = float(holding.market_value); shock = payload.shocks.get(holding.symbol, 0.0); position_pnl = value * shock; pnl += position_pnl
        positions.append({"symbol": holding.symbol, "value": value, "shock": shock, "pnl": position_pnl})
    total = float(summary.total_value); cutoff = summary.data_freshness_date or date.today()
    result = {"portfolio_value": total, "pnl": pnl, "pnl_percent": pnl / total if total else 0, "positions": positions, "assumptions": ["Direct symbol shocks are instantaneous and additive.", "Unspecified positions receive a zero shock.", "No liquidity, tax, fee, or second-order effects are modeled."]}
    row = ScenarioRun(portfolio_id=portfolio.id, name=payload.name, shocks_json=_json(payload.shocks), result_json=_json(result), data_cutoff=cutoff)
    db.add(row); db.commit(); db.refresh(row)
    return {"id": row.id, "name": row.name, "data_cutoff": cutoff, "shocks": payload.shocks, **result}


def create_monitoring_rule(db: Session, user: User, portfolio_id: str, rule_type: str, threshold: dict):
    portfolio = get_portfolio_or_404(db, user, portfolio_id)
    row = MonitoringRule(user_id=user.id, portfolio_id=portfolio.id, rule_type=rule_type, threshold_json=_json(threshold))
    db.add(row); db.commit(); db.refresh(row)
    return {"id": row.id, "portfolio_id": row.portfolio_id, "rule_type": row.rule_type, "threshold": threshold, "enabled": row.enabled}


def list_recommendations(db: Session, user: User):
    rows = db.scalars(select(Recommendation).where(Recommendation.user_id == user.id).order_by(Recommendation.created_at.desc())).all()
    return [{"id": r.id, "portfolio_id": r.portfolio_id, "trigger": r.trigger, "evidence": _load(r.evidence_json), "message": r.message, "status": r.status, "created_at": r.created_at} for r in rows]
