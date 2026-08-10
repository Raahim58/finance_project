import json
from datetime import UTC, date, datetime
from decimal import Decimal
from hashlib import sha256

import numpy as np
from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.quant import correlation_matrix, covariance_matrix, estimate_expected_returns, optimize, return_matrix, risk_contributions, risk_metrics
from app.models.market import MarketPrice
from app.models.portfolio import PortfolioHolding
from app.models.user import User
from app.models.workstation import (
    AnalysisRun,
    AllocationItem,
    AllocationSet,
    Instrument,
    InvestorFinancialProfile,
    InvestorFinancialProfileVersion,
    MonitoringRule,
    OptimizerRun,
    OptimizerAllocation,
    PortfolioIPSVersion,
    PortfolioIPS,
    Recommendation,
    ScenarioRun,
)
from app.schemas.workstation import IPSDraft, OptimizerRequest, RebalanceRequest, ScenarioRequest, VersionDraft
from app.services.ledger_service import cash_balance, replay_positions
from app.services.scenario_service import resolve_shock
from app.services.portfolio_service import get_portfolio_or_404, get_portfolio_summary


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _load(value: str) -> dict:
    return json.loads(value)


def save_profile_version(db: Session, user: User, payload: VersionDraft, confirm: bool = False):
    data = dict(payload.data)
    liquid_assets = float(data.get("liquid_assets", 0) or 0)
    liabilities = float(data.get("short_term_liabilities", 0) or 0)
    annual_expenses = float(data.get("annual_expenses", 0) or 0)
    data["derived_liquidity"] = liquid_assets - liabilities
    data["expense_coverage_months"] = ((liquid_assets - liabilities) / annual_expenses * 12) if annual_expenses > 0 else None
    answers = data.get("willingness_answers")
    if isinstance(answers, list) and answers:
        numeric = [float(value) for value in answers if isinstance(value, (int, float))]
        data["willingness_score"] = sum(numeric) / len(numeric) if numeric else None
    version = (db.scalar(select(func.max(InvestorFinancialProfileVersion.version)).where(InvestorFinancialProfileVersion.user_id == user.id)) or 0) + 1
    row = InvestorFinancialProfileVersion(
        user_id=user.id, version=version, status="confirmed" if confirm else "draft",
        profile_json=_json(data), confirmed_at=datetime.now(UTC) if confirm else None,
    )
    db.add(row); db.flush()
    header = db.scalar(select(InvestorFinancialProfile).where(InvestorFinancialProfile.user_id == user.id))
    if header is None:
        header = InvestorFinancialProfile(user_id=user.id)
        db.add(header)
    if confirm:
        header.current_version_id = row.id
    header.updated_at = datetime.now(UTC)
    db.commit(); db.refresh(row)
    return {"id": row.id, "version": row.version, "status": row.status, "data": data, "confirmed_at": row.confirmed_at}


def list_profile_versions(db: Session, user: User):
    rows = db.scalars(select(InvestorFinancialProfileVersion).where(InvestorFinancialProfileVersion.user_id == user.id).order_by(InvestorFinancialProfileVersion.version.desc())).all()
    return [{"id": r.id, "version": r.version, "status": r.status, "data": _load(r.profile_json), "confirmed_at": r.confirmed_at} for r in rows]


def save_ips_version(db: Session, user: User, portfolio_id: str, payload: IPSDraft, confirm: bool = False):
    portfolio = get_portfolio_or_404(db, user, portfolio_id)
    version = (db.scalar(select(func.max(PortfolioIPSVersion.version)).where(PortfolioIPSVersion.portfolio_id == portfolio.id)) or 0) + 1
    required_return = None
    if payload.starting_capital and payload.target_value and payload.horizon_years:
        def future_value(rate: float) -> float:
            years = payload.horizon_years
            growth = (1 + rate) ** years
            contributions = payload.annual_contribution * ((growth - 1) / rate) if rate != 0 else payload.annual_contribution * years
            return payload.starting_capital * growth + contributions
        low, high = -0.99, 5.0
        if not future_value(low) <= payload.target_value <= future_value(high):
            raise HTTPException(status_code=422, detail={"message": "Goal is outside the supported feasible return range", "minimum_future_value": future_value(low), "maximum_future_value": future_value(high)})
        for _ in range(100):
            midpoint = (low + high) / 2
            if future_value(midpoint) < payload.target_value: low = midpoint
            else: high = midpoint
        required_return = (low + high) / 2
    constraints = dict(payload.constraints)
    if payload.goal: constraints["goal"] = payload.goal
    if payload.benchmark_symbol: constraints["benchmark_symbol"] = payload.benchmark_symbol.upper()
    for key in ("max_instrument_weight", "max_sector_weight", "min_cash_weight", "target_volatility", "target_beta"):
        if key in constraints and not isinstance(constraints[key], (int, float)):
            raise HTTPException(status_code=422, detail=f"{key} must be numeric")
    row = PortfolioIPSVersion(
        portfolio_id=portfolio.id, version=version, status="confirmed" if confirm else "draft",
        constraints_json=_json(constraints), required_return=required_return,
        confirmed_at=datetime.now(UTC) if confirm else None,
    )
    db.add(row); db.flush()
    header = db.scalar(select(PortfolioIPS).where(PortfolioIPS.portfolio_id == portfolio.id))
    if header is None:
        header = PortfolioIPS(portfolio_id=portfolio.id)
        db.add(header)
    if confirm:
        header.current_version_id = row.id
        portfolio.selected_ips_version_id = row.id
    header.updated_at = datetime.now(UTC)
    db.commit(); db.refresh(row)
    return {"id": row.id, "version": row.version, "status": row.status, "constraints": constraints, "required_return": float(row.required_return) if row.required_return is not None else None, "confirmed_at": row.confirmed_at}


def list_ips_versions(db: Session, user: User, portfolio_id: str):
    portfolio = get_portfolio_or_404(db, user, portfolio_id)
    rows = db.scalars(select(PortfolioIPSVersion).where(PortfolioIPSVersion.portfolio_id == portfolio.id).order_by(PortfolioIPSVersion.version.desc())).all()
    return [{"id": r.id, "version": r.version, "status": r.status, "constraints": _load(r.constraints_json), "required_return": float(r.required_return) if r.required_return is not None else None, "confirmed_at": r.confirmed_at} for r in rows]


def ips_compliance(db: Session, user: User, portfolio_id: str):
    portfolio = get_portfolio_or_404(db, user, portfolio_id)
    version = db.get(PortfolioIPSVersion, portfolio.selected_ips_version_id) if portfolio.selected_ips_version_id else None
    if version is None:
        return {"portfolio_id": portfolio.id, "ips_version_id": None, "compliant": False, "violations": [{"code": "missing_confirmed_ips", "message": "Confirm an IPS before evaluating compliance."}], "evaluated_at": datetime.now(UTC)}
    constraints = _load(version.constraints_json)
    summary = get_portfolio_summary(db, user, portfolio.id)
    violations = []
    total = float(summary.total_value)
    max_instrument = constraints.get("max_instrument_weight")
    excluded = {str(value).upper() for value in constraints.get("excluded_instruments", [])}
    allowed = {str(value).upper() for value in constraints.get("allowed_instruments", [])}
    sector_values: dict[str, float] = {}
    for holding in summary.holdings:
        weight = float(holding.market_value) / total if total else 0
        sector_values[holding.sector] = sector_values.get(holding.sector, 0) + weight
        if max_instrument is not None and weight > float(max_instrument):
            violations.append({"code": "max_instrument_weight", "symbol": holding.symbol, "actual": weight, "limit": float(max_instrument)})
        if holding.symbol.upper() in excluded or (allowed and holding.symbol.upper() not in allowed):
            violations.append({"code": "instrument_not_allowed", "symbol": holding.symbol})
    max_sector = constraints.get("max_sector_weight")
    if max_sector is not None:
        for sector, weight in sector_values.items():
            if weight > float(max_sector): violations.append({"code": "max_sector_weight", "sector": sector, "actual": weight, "limit": float(max_sector)})
    min_cash = constraints.get("min_cash_weight")
    cash_weight = float(summary.cash_balance) / total if total else 0
    if min_cash is not None and cash_weight < float(min_cash):
        violations.append({"code": "min_cash_weight", "actual": cash_weight, "limit": float(min_cash)})
    return {"portfolio_id": portfolio.id, "ips_version_id": version.id, "compliant": not violations, "violations": violations, "evaluated_at": datetime.now(UTC)}


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
    correlation = correlation_matrix(returns)
    summary = get_portfolio_summary(db, user, portfolio_id)
    market_values = {row.symbol: float(row.market_value) for row in summary.holdings}
    total = sum(market_values.values())
    weights = np.array([market_values[s] / total for s in symbols]) if total else np.full(len(symbols), 1 / len(symbols))
    ledger_values: list[float] = []
    ledger_days: list[date] = []
    price_maps = {symbol: {day: prices[index][day_index] for day_index, day in enumerate(days)} for index, symbol in enumerate(symbols)}
    for day in days:
        if portfolio.history_start and day < portfolio.history_start:
            continue
        positions = replay_positions(db, portfolio.id, day)
        if not positions:
            continue
        value = float(cash_balance(db, portfolio.id, portfolio.base_currency, day))
        missing = False
        for position in positions.values():
            if position.symbol not in price_maps or day not in price_maps[position.symbol]:
                missing = True; break
            value += float(position.quantity) * price_maps[position.symbol][day]
        if not missing:
            ledger_days.append(day); ledger_values.append(value)
    if len(ledger_values) >= 31 and all(value > 0 for value in ledger_values):
        portfolio_returns = np.asarray(ledger_values[1:]) / np.asarray(ledger_values[:-1]) - 1
        metrics: dict[str, object] = risk_metrics(portfolio_returns).to_dict()
        metrics["history_method"] = "ledger_positions_and_cash"
    else:
        metrics = {"available": False, "reason": "At least 30 post-baseline ledger return observations are required", "sample_size": max(len(ledger_values) - 1, 0)}
    metrics["concentration_hhi"] = float(weights @ weights)
    metrics["variance"] = float(weights @ covariance @ weights)
    contributions = risk_contributions(weights, covariance)
    fingerprint_data = {"portfolio_id": portfolio.id, "holding_version": [(row.symbol, str(row.quantity), str(row.average_cost)) for row in summary.holdings], "data_cutoff": days[-1].isoformat(), "shrinkage": shrinkage, "history_start": portfolio.history_start.isoformat() if portfolio.history_start else None}
    fingerprint = sha256(_json(fingerprint_data).encode()).hexdigest()
    run = db.scalar(select(AnalysisRun).where(AnalysisRun.input_fingerprint == fingerprint))
    result_data = {"data_cutoff": days[-1].isoformat(), "symbols": symbols, "sample_size": len(days) - 1, "annualization": 252, "covariance_shrinkage": shrinkage, "portfolio": metrics, "covariance": covariance.tolist(), "correlation": correlation.tolist(), "risk_contributions": dict(zip(symbols, [float(value) for value in contributions["percentage"]], strict=True)), "warnings": [] if portfolio.history_complete else ["Performance before the migration/opening-balance baseline is unavailable."]}
    if run is None:
        run = AnalysisRun(portfolio_id=portfolio.id, analysis_type="portfolio_quant", input_fingerprint=fingerprint, data_cutoff=days[-1], estimator_json=_json({"covariance": "diagonal_shrinkage", "lambda": shrinkage, "annualization": 252}), code_version="quant-v1", result_json=_json(result_data), artifact_hashes_json="[]", status="completed")
        db.add(run); db.commit(); db.refresh(run)
    result_data["run_id"] = run.id
    result_data["data_cutoff"] = days[-1]
    return result_data


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
    lower = [payload.minimum_weight] * len(symbols)
    upper = [payload.maximum_weight] * len(symbols)
    ips_version = db.get(PortfolioIPSVersion, portfolio.selected_ips_version_id) if portfolio.selected_ips_version_id else None
    constraints = _load(ips_version.constraints_json) if ips_version else {}
    excluded = {str(value).upper() for value in constraints.get("excluded_instruments", [])}
    allowed = {str(value).upper() for value in constraints.get("allowed_instruments", [])}
    for index, symbol in enumerate(symbols):
        if symbol in excluded or (allowed and symbol not in allowed): upper[index] = 0
        if "max_instrument_weight" in constraints: upper[index] = min(upper[index], float(constraints["max_instrument_weight"]))
    unsupported = [key for key in ("max_drawdown", "derivatives_rule") if key in constraints]
    if unsupported:
        raise HTTPException(status_code=422, detail={"message": "IPS contains constraints that cannot be represented by this optimizer", "unsupported_constraints": unsupported})
    betas = np.array([payload.beta_assumptions[s] for s in symbols]) if payload.beta_assumptions else None
    budgets = np.array([payload.risk_budgets[s] for s in symbols]) if payload.risk_budgets else None
    result = optimize(
        covariance, objective=payload.objective, expected_returns=estimate.values if estimate else None,
        target_return=payload.target_return, target_volatility=payload.target_volatility,
        target_beta=payload.target_beta, betas=betas, risk_budgets=budgets,
        risk_free_rate=payload.risk_free_rate, lower_bounds=lower, upper_bounds=upper,
    )
    assumptions_data = {"covariance": "diagonal_shrinkage", "covariance_shrinkage": payload.covariance_shrinkage, "expected_returns": estimate.assumptions if estimate else None, "annualization": 252}
    result_data = result.to_dict()
    row = OptimizerRun(portfolio_id=portfolio.id, objective=payload.objective, expected_return_method=payload.expected_return_method, ips_version_id=ips_version.id if ips_version else None, data_cutoff=days[-1], bounds_json=_json({"lower": lower, "upper": upper}), solver=str(result.diagnostics.get("solver")) if result.diagnostics.get("solver") else None, seed=0, input_json=_json(payload.model_dump(mode="json")), result_json=_json({**result_data, "symbols": symbols}), status=result.status, diagnostics_json=_json(result.diagnostics))
    db.add(row); db.flush()
    if result.status == "optimal":
        instruments = {item.symbol: item for item in db.scalars(select(Instrument).where(Instrument.symbol.in_(symbols)))}
        proposal_version = (db.scalar(select(func.max(AllocationSet.version)).where(AllocationSet.portfolio_id == portfolio.id, AllocationSet.kind == "optimized")) or 0) + 1
        proposal = AllocationSet(portfolio_id=portfolio.id, kind="optimized", version=proposal_version, status="proposal", assumptions_json=_json(assumptions_data), base_value=Decimal(str(get_portfolio_summary(db, user, portfolio.id).total_value)), created_by_user_id=user.id)
        db.add(proposal); db.flush()
        for symbol, weight in zip(symbols, result.weights, strict=True):
            if symbol in instruments:
                db.add(OptimizerAllocation(optimizer_run_id=row.id, instrument_id=instruments[symbol].id, weight=Decimal(str(weight))))
                db.add(AllocationItem(allocation_set_id=proposal.id, symbol=symbol, instrument_id=instruments[symbol].id, is_cash=False, target_weight=Decimal(str(weight)), locked=False))
    db.commit(); db.refresh(row)
    return {"id": row.id, "status": result.status, "objective": payload.objective, "expected_return_method": payload.expected_return_method, "data_cutoff": days[-1], "symbols": symbols, "weights": dict(zip(symbols, result.weights, strict=True)) if result.weights else {}, "expected_return": result.expected_return, "volatility": result.volatility, "diagnostics": result.diagnostics, "assumptions": assumptions_data}


def security_quant(db: Session, instrument_id: str):
    instrument = db.get(Instrument, instrument_id)
    if instrument is None:
        raise HTTPException(status_code=404, detail="Instrument not found")
    rows = list(db.scalars(select(MarketPrice).where(MarketPrice.symbol == instrument.symbol).order_by(MarketPrice.trade_date)))
    if len(rows) < 31:
        raise HTTPException(status_code=422, detail="At least 31 price observations are required")
    values = np.array([float(row.close) for row in rows])
    returns = values[1:] / values[:-1] - 1
    return {"instrument_id": instrument.id, "symbol": instrument.symbol, "data_cutoff": rows[-1].trade_date, "sample_size": len(returns), "annualization": 252, "metrics": risk_metrics(returns).to_dict(), "source": rows[-1].source}


def efficient_frontier(db: Session, user: User, portfolio_id: str, points: int = 20):
    portfolio = get_portfolio_or_404(db, user, portfolio_id)
    symbols, days, prices = _aligned_prices(db, portfolio.id, None, None)
    returns = return_matrix(prices)
    covariance = covariance_matrix(returns, 0.20)
    estimates = estimate_expected_returns("historical_shrunk", returns).values
    frontier = []
    for target in np.linspace(float(np.min(estimates)), float(np.max(estimates)), points):
        result = optimize(covariance, objective="target_return_minimum_variance", expected_returns=estimates, target_return=float(target))
        if result.status == "optimal": frontier.append({"target_return": float(target), "expected_return": result.expected_return, "volatility": result.volatility, "weights": dict(zip(symbols, result.weights, strict=True))})
    return {"portfolio_id": portfolio.id, "data_cutoff": days[-1], "estimator": "historical_shrunk_comparison", "points": frontier}


def rebalance_preview(db: Session, user: User, portfolio_id: str, payload: RebalanceRequest):
    portfolio = get_portfolio_or_404(db, user, portfolio_id)
    if abs(sum(payload.target_weights.values()) - 1) > 1e-6 or any(value < 0 for value in payload.target_weights.values()):
        raise HTTPException(status_code=422, detail="Target weights must be non-negative and sum to one")
    summary = get_portfolio_summary(db, user, portfolio.id)
    total = float(summary.total_value)
    current = {holding.symbol: float(holding.market_value) for holding in summary.holdings}
    trades = []
    residual_cash = float(summary.cash_balance)
    warnings = []
    for symbol, weight in payload.target_weights.items():
        instrument = db.scalar(select(Instrument).where(Instrument.symbol == symbol.upper()))
        price = db.scalar(select(MarketPrice).where(MarketPrice.symbol == symbol.upper()).order_by(MarketPrice.trade_date.desc()))
        if instrument is None or price is None:
            warnings.append(f"{symbol.upper()}: missing instrument or current price")
            continue
        target_amount = total * weight
        difference = target_amount - current.get(symbol.upper(), 0)
        if abs(difference) < payload.minimum_trade_value:
            continue
        metadata = _load(instrument.metadata_json)
        lot_size = float(metadata.get("lot_size", 1) or 1)
        quantity = np.floor(abs(difference) / float(price.close) / lot_size) * lot_size
        gross = quantity * float(price.close)
        fee = gross * payload.fee_rate
        side = "buy" if difference > 0 else "sell"
        residual_cash += (-gross - fee) if side == "buy" else (gross - fee)
        trades.append({"symbol": symbol.upper(), "side": side, "quantity": float(quantity), "price": float(price.close), "gross_amount": gross, "estimated_fee": fee, "before_weight": current.get(symbol.upper(), 0) / total if total else 0, "target_weight": weight})
    if residual_cash < -1e-6:
        warnings.append("Proposed buys exceed available cash after estimated fees.")
    return {"portfolio_id": portfolio.id, "data_cutoff": summary.data_freshness_date, "trades": trades, "residual_cash": residual_cash, "warnings": warnings}


def run_scenario(db: Session, user: User, portfolio_id: str, payload: ScenarioRequest):
    portfolio = get_portfolio_or_404(db, user, portfolio_id)
    summary = get_portfolio_summary(db, user, portfolio_id)
    positions, pnl = [], 0.0
    for holding in summary.holdings:
        value = float(holding.market_value)
        instrument = db.scalar(select(Instrument).where(Instrument.symbol == holding.symbol))
        shock, mapping_sources = resolve_shock(instrument, {key.upper(): value for key, value in payload.shocks.items()}, payload.sector_shocks, payload.factor_shocks) if instrument else (payload.shocks.get(holding.symbol, 0.0), [])
        position_pnl = value * shock; pnl += position_pnl
        positions.append({"symbol": holding.symbol, "sector": holding.sector, "value": value, "shock": shock, "pnl": position_pnl, "mapping_sources": mapping_sources})
    total = float(summary.total_value); cutoff = summary.data_freshness_date or date.today()
    result = {"portfolio_value": total, "pnl": pnl, "pnl_percent": pnl / total if total else 0, "positions": positions, "assumptions": ["Direct instrument shocks override sector/factor mappings to avoid double counting.", "Sector and factor shocks are additive when no direct shock exists.", "No liquidity, tax, fee, or second-order effects are modeled."]}
    all_shocks = {"instruments": payload.shocks, "sectors": payload.sector_shocks, "factors": payload.factor_shocks}
    row = ScenarioRun(portfolio_id=portfolio.id, name=payload.name, shocks_json=_json(all_shocks), result_json=_json(result), data_cutoff=cutoff, assumptions_json=_json({"mapping_order": ["instrument", "sector", "factor"]}), status="completed")
    db.add(row); db.commit(); db.refresh(row)
    return {"id": row.id, "name": row.name, "data_cutoff": cutoff, "shocks": payload.shocks, **result}


def create_monitoring_rule(db: Session, user: User, portfolio_id: str, rule_type: str, threshold: dict, deduplication_window_minutes: int = 1440):
    portfolio = get_portfolio_or_404(db, user, portfolio_id)
    row = MonitoringRule(user_id=user.id, portfolio_id=portfolio.id, rule_type=rule_type, threshold_json=_json(threshold), deduplication_window_minutes=deduplication_window_minutes)
    db.add(row); db.commit(); db.refresh(row)
    return {"id": row.id, "portfolio_id": row.portfolio_id, "rule_type": row.rule_type, "threshold": threshold, "enabled": row.enabled, "deduplication_window_minutes": row.deduplication_window_minutes}


def list_recommendations(db: Session, user: User):
    rows = db.scalars(select(Recommendation).where(Recommendation.user_id == user.id).order_by(Recommendation.created_at.desc())).all()
    return [{"id": r.id, "portfolio_id": r.portfolio_id, "trigger": r.trigger, "evidence": _load(r.evidence_json), "message": r.message, "status": r.status, "created_at": r.created_at} for r in rows]


def list_optimizer_runs(db: Session, user: User, portfolio_id: str):
    portfolio = get_portfolio_or_404(db, user, portfolio_id)
    rows = db.scalars(
        select(OptimizerRun)
        .where(OptimizerRun.portfolio_id == portfolio.id)
        .order_by(OptimizerRun.created_at.desc())
    ).all()
    return [
        {
            "id": row.id,
            "portfolio_id": row.portfolio_id,
            "objective": row.objective,
            "expected_return_method": row.expected_return_method,
            "ips_version_id": row.ips_version_id,
            "data_cutoff": row.data_cutoff,
            "bounds": _load(row.bounds_json),
            "solver": row.solver,
            "result": _load(row.result_json),
            "status": row.status,
            "diagnostics": _load(row.diagnostics_json),
            "created_at": row.created_at,
        }
        for row in rows
    ]


def list_scenario_runs(db: Session, user: User, portfolio_id: str):
    portfolio = get_portfolio_or_404(db, user, portfolio_id)
    rows = db.scalars(
        select(ScenarioRun)
        .where(ScenarioRun.portfolio_id == portfolio.id)
        .order_by(ScenarioRun.created_at.desc())
    ).all()
    return [
        {
            "id": row.id,
            "portfolio_id": row.portfolio_id,
            "scenario_definition_id": row.scenario_definition_id,
            "name": row.name,
            "shocks": _load(row.shocks_json),
            "result": _load(row.result_json),
            "data_cutoff": row.data_cutoff,
            "assumptions": _load(row.assumptions_json),
            "status": row.status,
            "created_at": row.created_at,
        }
        for row in rows
    ]
