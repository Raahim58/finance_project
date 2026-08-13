import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from threading import Lock
from time import monotonic

import numpy as np
from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.quant import (
    correlation_matrix,
    covariance_matrix,
    estimate_expected_returns,
    optimize,
    performance_ratios,
    regression_metrics,
    return_matrix,
    risk_contributions,
    risk_metrics,
)
from app.domain.analytics_contract import DEFAULT_MAX_CASH_WEIGHT, WEIGHT_TOLERANCE, weight_diagnostics
from app.models.market import MarketPrice
from app.models.portfolio import PortfolioHolding
from app.models.user import User
from app.models.workstation import (
    AnalysisRun,
    AllocationItem,
    AllocationSet,
    CorporateAction,
    Instrument,
    InvestorFinancialProfile,
    InvestorFinancialProfileVersion,
    MonitoringRule,
    MacroObservation,
    MacroSeries,
    MarketObservation,
    OptimizerRun,
    OptimizerAllocation,
    PortfolioIPSVersion,
    PortfolioIPS,
    Recommendation,
    ScenarioRun,
)
from app.schemas.workstation import IPSDraft, OptimizerRequest, RebalanceRequest, ScenarioRequest, VersionDraft
from app.services.audit_service import record_event
from app.services.ledger_service import cash_balance, replay_positions
from app.services.scenario_service import resolve_shock
from app.services.portfolio_service import get_portfolio_or_404, get_portfolio_performance, get_portfolio_summary
from app.services.risk_profile_service import RISK_ORDER as _RISK_ORDER, assess_risk_profile
from app.services.canonical_market_service import latest_price, price_series
from app.services.compliance_service import evaluate_ips_constraints


_ALIGNED_PRICE_TTL_SECONDS = 60
_aligned_price_cache: dict[tuple[object, ...], tuple[float, tuple[str, ...], tuple[date, ...], tuple[tuple[float, ...], ...]]] = {}
_aligned_price_cache_lock = Lock()


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


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
    data["risk_assessment"] = assess_risk_profile(data)
    assessment = data["risk_assessment"]
    confirmed = assessment.get("confirmed_tolerance")
    reconciled = assessment.get("reconciled_tolerance")
    if confirm and confirmed and reconciled and _RISK_ORDER[str(confirmed)] > _RISK_ORDER[str(reconciled)]:
        raise HTTPException(status_code=422, detail="Confirmed risk tolerance cannot exceed the more restrictive calculated capacity and willingness.")
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
    if payload.overall_risk_tolerance and payload.risk_capacity and payload.risk_willingness:
        ceiling = min(_RISK_ORDER[payload.risk_capacity], _RISK_ORDER[payload.risk_willingness])
        if _RISK_ORDER[payload.overall_risk_tolerance] > ceiling:
            raise HTTPException(status_code=422, detail="Overall risk tolerance cannot exceed the more restrictive of capacity and willingness.")
    version = (db.scalar(select(func.max(PortfolioIPSVersion.version)).where(PortfolioIPSVersion.portfolio_id == portfolio.id)) or 0) + 1
    required_return = None
    valuation_date = payload.valuation_date or date.today()
    horizon_years = payload.horizon_years
    if payload.target_date:
        horizon_years = (payload.target_date - valuation_date).days / 365.2425
    if payload.starting_capital and payload.target_value and horizon_years:
        target_value = payload.target_value
        if payload.target_value_is_real:
            target_value *= (1 + float(payload.inflation_rate)) ** horizon_years
        dated = [(item.contribution_date, item.amount) for item in payload.dated_contributions]
        if any(day < valuation_date or (payload.target_date and day > payload.target_date) for day, _ in dated):
            raise HTTPException(status_code=422, detail="Dated contributions must fall between valuation_date and target_date")

        def future_value(rate: float) -> float:
            growth = (1 + rate) ** horizon_years
            annual_contributions = payload.annual_contribution * ((growth - 1) / rate) if rate != 0 else payload.annual_contribution * horizon_years
            dated_value = 0.0
            for contribution_date, amount in dated:
                remaining = ((payload.target_date or (valuation_date + timedelta(days=round(horizon_years * 365.2425)))) - contribution_date).days / 365.2425
                dated_value += amount * (1 + rate) ** max(remaining, 0)
            return payload.starting_capital * growth + annual_contributions + dated_value
        low, high = -0.99, 5.0
        if not future_value(low) <= target_value <= future_value(high):
            raise HTTPException(status_code=422, detail={"message": "Goal is outside the supported feasible return range", "minimum_future_value": future_value(low), "maximum_future_value": future_value(high)})
        for _ in range(100):
            midpoint = (low + high) / 2
            if future_value(midpoint) < target_value: low = midpoint
            else: high = midpoint
        required_return = (low + high) / 2
    constraints = dict(payload.constraints)
    objective_inputs = {
        "starting_capital": payload.starting_capital,
        "target_value": payload.target_value,
        "horizon_years": horizon_years,
        "annual_contribution": payload.annual_contribution,
        "valuation_date": valuation_date.isoformat(),
        "target_date": payload.target_date.isoformat() if payload.target_date else None,
    }
    constraints["objective_inputs"] = {key: value for key, value in objective_inputs.items() if value is not None}
    if payload.goal: constraints["goal"] = payload.goal
    performance_benchmark = payload.performance_benchmark_symbol or payload.benchmark_symbol
    if performance_benchmark:
        constraints["performance_benchmark_symbol"] = performance_benchmark.upper()
        # Compatibility for older clients. New analytics never use this as CAPM proxy.
        constraints["benchmark_symbol"] = performance_benchmark.upper()
    if payload.capm_market_proxy_symbol:
        constraints["capm_market_proxy_symbol"] = payload.capm_market_proxy_symbol.upper()
    typed_constraints = {
        "risk_capacity": payload.risk_capacity,
        "risk_willingness": payload.risk_willingness,
        "overall_risk_tolerance": payload.overall_risk_tolerance,
        "loss_budget": payload.loss_budget,
        "liquidity_requirement": payload.liquidity_requirement,
        "allowed_asset_types": payload.allowed_asset_types,
        "allowed_currencies": payload.allowed_currencies,
        "shariah_only": payload.shariah_only,
        "leverage_allowed": payload.leverage_allowed,
        "derivatives_allowed": payload.derivatives_allowed,
        "tax_notes": payload.tax_notes,
    }
    constraints.update({key: value for key, value in typed_constraints.items() if value is not None})
    if required_return is not None:
        constraints["required_return_method"] = {
            "method": "dated_cash_flow_future_value_bisection",
            "valuation_date": valuation_date.isoformat(),
            "target_date": payload.target_date.isoformat() if payload.target_date else None,
            "horizon_years": horizon_years,
            "target_value_is_real": payload.target_value_is_real,
            "inflation_rate": payload.inflation_rate,
            "dated_contributions": [{"date": day.isoformat(), "amount": amount} for day, amount in dated],
            "annual_contribution_timing": "end_of_year",
        }
    for key in ("max_instrument_weight", "max_sector_weight", "min_cash_weight", "max_cash_weight", "target_volatility", "target_beta", "operational_cash_return"):
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
        previous_version = db.get(PortfolioIPSVersion, header.current_version_id) if header.current_version_id else None
        header.current_version_id = row.id
        portfolio.selected_ips_version_id = row.id
        record_event(
            db, user, event_type="ips_confirmed", entity_type="ips_version", entity_id=row.id, portfolio_id=portfolio.id,
            entity_version=row.version,
            previous_state={"version": previous_version.version, "constraints": json.loads(previous_version.constraints_json)} if previous_version else None,
            new_state={"version": row.version, "constraints": constraints, "required_return": float(row.required_return) if row.required_return is not None else None},
            note="IPS mandate confirmed as a new immutable version.",
        )
    header.updated_at = datetime.now(UTC)
    db.commit(); db.refresh(row)
    analysis = {
        "available": row.required_return is not None,
        "annual_rate": float(row.required_return) if row.required_return is not None else None,
        "calculation_type": constraints.get("required_return_method", {}).get("method") if isinstance(constraints.get("required_return_method"), dict) else None,
        "assumptions": constraints.get("objective_inputs", {}),
        "diagnostics": [] if row.required_return is not None else ["Starting capital, target value, and a positive horizon are required to calculate the required return."],
    }
    return {"id": row.id, "version": row.version, "status": row.status, "constraints": constraints, "required_return": float(row.required_return) if row.required_return is not None else None, "required_return_analysis": analysis, "confirmed_at": row.confirmed_at}


def list_ips_versions(db: Session, user: User, portfolio_id: str):
    portfolio = get_portfolio_or_404(db, user, portfolio_id)
    rows = db.scalars(select(PortfolioIPSVersion).where(PortfolioIPSVersion.portfolio_id == portfolio.id).order_by(PortfolioIPSVersion.version.desc())).all()
    results = []
    for row in rows:
        constraints = _load(row.constraints_json)
        available = row.required_return is not None
        results.append({"id": row.id, "version": row.version, "status": row.status, "constraints": constraints, "required_return": float(row.required_return) if available else None, "required_return_analysis": {"available": available, "annual_rate": float(row.required_return) if available else None, "calculation_type": constraints.get("required_return_method", {}).get("method") if isinstance(constraints.get("required_return_method"), dict) else None, "assumptions": constraints.get("objective_inputs", {}), "diagnostics": [] if available else ["Starting capital, target value, and a positive horizon are required to calculate the required return."]}, "confirmed_at": row.confirmed_at})
    return results


def ips_compliance(db: Session, user: User, portfolio_id: str):
    portfolio = get_portfolio_or_404(db, user, portfolio_id)
    version = db.get(PortfolioIPSVersion, portfolio.selected_ips_version_id) if portfolio.selected_ips_version_id else None
    if version is None:
        missing = {"code": "missing_confirmed_ips", "label": "Confirmed IPS", "status": "NOT_EVALUATED", "message": "Confirm an IPS before evaluating compliance.", "severity": "availability"}
        return {"portfolio_id": portfolio.id, "ips_version_id": None, "context": "current", "status": "NOT_EVALUATED", "compliant": False, "checks": [missing], "violations": [], "not_evaluated": [missing], "evaluated_at": datetime.now(UTC)}
    constraints = _load(version.constraints_json)
    summary = get_portfolio_summary(db, user, portfolio.id)
    total = float(summary.total_value)
    instruments = {row.symbol: row for row in db.scalars(select(Instrument).where(Instrument.symbol.in_([holding.symbol for holding in summary.holdings])))}
    positions = []
    for holding in summary.holdings:
        instrument = instruments.get(holding.symbol)
        metadata = _load(instrument.metadata_json) if instrument and instrument.metadata_json else {}
        positions.append({"symbol": holding.symbol, "weight": float(holding.market_value) / total if total else 0.0, "sector": holding.sector, "shariah_eligible": metadata.get("shariah_compliant")})
    positions.append({"symbol": "CASH", "weight": float(summary.cash_balance) / total if total else 0.0, "sector": "Cash"})
    modeled_inputs: dict[str, object] = {"liquid_assets": float(summary.cash_balance), "data_cutoff": summary.data_freshness_date, "estimator": "aligned_price_covariance_v1"}
    try:
        quant = portfolio_quant(db, user, portfolio.id)
        variance = quant.get("portfolio", {}).get("variance")
        benchmark = quant.get("benchmark") if isinstance(quant.get("benchmark"), dict) else {}
        benchmark_metrics = benchmark.get("metrics") if isinstance(benchmark.get("metrics"), dict) else {}
        modeled_inputs.update({
            "portfolio_volatility": float(np.sqrt(max(float(variance), 0))) if variance is not None else None,
            "portfolio_beta": benchmark_metrics.get("beta"),
            "risk_contributions": quant.get("risk_contributions"),
            "data_cutoff": quant.get("data_cutoff"),
        })
    except HTTPException:
        # Availability is reported per modeled check; cash and weight checks still run.
        pass
    result = evaluate_ips_constraints(constraints, positions, ips_version_id=version.id, valuation_complete=summary.valuation_complete, unpriced_symbols=summary.unpriced_symbols, context="current", modeled_inputs=modeled_inputs)
    return {"portfolio_id": portfolio.id, **result, "evaluated_at": datetime.now(UTC)}


def _aligned_prices(db: Session, portfolio_id: str, start: date | None, end: date | None):
    holding_rows = list(
        db.execute(
            select(PortfolioHolding.symbol, PortfolioHolding.updated_at)
            .where(PortfolioHolding.portfolio_id == portfolio_id)
            .order_by(PortfolioHolding.symbol)
        )
    )
    symbols = [row.symbol for row in holding_rows]
    return _aligned_symbol_prices(db, symbols, start, end, cache_key=(portfolio_id, tuple((row.symbol, row.updated_at) for row in holding_rows)))


def _aligned_symbol_prices(db: Session, symbols: list[str], start: date | None, end: date | None, cache_key: object | None = None):
    """Align canonical prices for an analytical universe without changing holdings."""
    symbols = sorted({symbol.upper() for symbol in symbols})
    if len(symbols) < 2:
        raise HTTPException(status_code=422, detail="At least two securities are required")
    instrument_ids = list(db.scalars(select(Instrument.id).where(Instrument.symbol.in_(symbols))))
    observation_stamp = db.execute(
        select(func.count(MarketObservation.id), func.max(MarketObservation.effective_at))
        .where(
            MarketObservation.instrument_id.in_(instrument_ids),
            MarketObservation.is_selected.is_(True),
            MarketObservation.frequency == "daily",
        )
    ).one()
    legacy_stamp = db.execute(
        select(func.count(MarketPrice.id), func.max(MarketPrice.trade_date), func.max(MarketPrice.ingested_at))
        .where(MarketPrice.symbol.in_(symbols))
    ).one()
    key = (
        cache_key or tuple(symbols),
        start,
        end,
        tuple(observation_stamp),
        tuple(legacy_stamp),
    )
    now = monotonic()
    with _aligned_price_cache_lock:
        cached = _aligned_price_cache.get(key)
        if cached and cached[0] > now:
            return list(cached[1]), list(cached[2]), [list(column) for column in cached[3]]
        by_symbol = {symbol: {} for symbol in symbols}
        for symbol in symbols:
            for row in price_series(db, symbol, start, end):
                by_symbol[symbol][row.trade_date] = float(row.close)
        aligned_dates = sorted(set.intersection(*(set(values) for values in by_symbol.values())))
        if len(aligned_dates) < 31:
            raise HTTPException(status_code=422, detail="At least 31 aligned price observations are required")
        prices = [[by_symbol[symbol][day] for day in aligned_dates] for symbol in symbols]
        for stale_key, value in list(_aligned_price_cache.items()):
            if value[0] <= now:
                _aligned_price_cache.pop(stale_key, None)
        if len(_aligned_price_cache) >= 32:
            _aligned_price_cache.pop(next(iter(_aligned_price_cache)))
        _aligned_price_cache[key] = (
            now + _ALIGNED_PRICE_TTL_SECONDS,
            tuple(symbols),
            tuple(aligned_dates),
            tuple(tuple(column) for column in prices),
        )
        return symbols, aligned_dates, prices


def _selected_ips_constraints(db: Session, portfolio) -> dict[str, object]:
    version = db.get(PortfolioIPSVersion, portfolio.selected_ips_version_id) if portfolio.selected_ips_version_id else None
    return _load(version.constraints_json) if version else {}


def _benchmark_symbol(db: Session, portfolio, constraints: dict[str, object]) -> str | None:
    configured = constraints.get("performance_benchmark_symbol") or constraints.get("benchmark_symbol")
    if configured:
        return str(configured).strip().upper()
    instrument = db.get(Instrument, portfolio.benchmark_instrument_id) if portfolio.benchmark_instrument_id else None
    return instrument.symbol if instrument else None


def _capm_market_proxy_symbol(db: Session, constraints: dict[str, object]) -> tuple[str | None, list[str]]:
    configured = constraints.get("capm_market_proxy_symbol")
    if not configured:
        return None, ["No CAPM market proxy is configured separately from the performance benchmark."]
    symbol = str(configured).strip().upper()
    instrument = db.scalar(select(Instrument).where(Instrument.symbol == symbol))
    if instrument is None:
        return None, [f"CAPM market proxy {symbol} is not in the instrument master."]
    metadata = _load(instrument.metadata_json)
    approved = instrument.instrument_type.lower() in {"index", "total_return_index"} and metadata.get("broad_market_proxy") is True
    if not approved:
        return None, [f"{symbol} is not an approved broad-index CAPM market proxy; individual securities are rejected."]
    warnings = [] if instrument.instrument_type.lower() == "total_return_index" or metadata.get("return_basis") == "total_return" else [f"{symbol} uses a price-return index; distributions are not included."]
    return symbol, warnings


def _benchmark_returns_for_optimizer(db: Session, symbol: str | None, days: list[date]) -> np.ndarray | None:
    if not symbol:
        return None
    by_date = {row.trade_date: float(row.close) for row in price_series(db, symbol)}
    if any(day not in by_date for day in days):
        return None
    prices = np.asarray([by_date[day] for day in days], dtype=float)
    return prices[1:] / prices[:-1] - 1


def _effective_risk_free_rate(db: Session, as_of: date, series_key: str | None = None) -> dict[str, object] | None:
    """Resolve an observed, effective-dated annual risk-free input.

    No default rate is invented. A series is eligible only when explicitly selected,
    marked ``is_risk_free`` in metadata, or uses a recognized SBP risk-free key.
    """
    preferred_keys = [series_key] if series_key else ["sbp.tbill.3m_yield", "pk.tbill.3m_yield", "government.tbill.3m_yield"]
    candidates = list(db.scalars(select(MacroSeries)))
    ranked = []
    for series in candidates:
        metadata = _load(series.metadata_json)
        if series.key not in preferred_keys and not metadata.get("is_risk_free"):
            continue
        priority = preferred_keys.index(series.key) if series.key in preferred_keys else len(preferred_keys)
        ranked.append((priority, series))
    for _, series in sorted(ranked, key=lambda item: item[0]):
        observation = db.scalar(
            select(MacroObservation)
            .where(
                MacroObservation.series_id == series.id,
                MacroObservation.is_selected.is_(True),
                MacroObservation.effective_date <= as_of,
            )
            .order_by(MacroObservation.effective_date.desc(), MacroObservation.revision.desc())
        )
        if observation is None:
            continue
        value = float(observation.value)
        unit = series.unit.strip().lower()
        annual_rate = value / 100 if unit in {"%", "percent", "percentage", "pct"} else value
        return {
            "annual_rate": annual_rate,
            "series_key": series.key,
            "effective_date": observation.effective_date,
            "release_at": observation.release_at,
            "artifact_id": observation.artifact_id,
        }
    return None


def _benchmark_analysis(
    db: Session,
    benchmark_symbol: str,
    portfolio_returns_by_date: dict[date, float],
    risk_free_rate: float,
) -> dict[str, object]:
    rows = price_series(db, benchmark_symbol)
    benchmark_returns = {
        rows[index].trade_date: float(rows[index].close / rows[index - 1].close - 1)
        for index in range(1, len(rows))
        if rows[index - 1].close > 0
    }
    aligned_dates = sorted(set(portfolio_returns_by_date) & set(benchmark_returns))
    if len(aligned_dates) < 60:
        return {
            "available": False,
            "symbol": benchmark_symbol,
            "reason": "At least 60 aligned portfolio and benchmark return observations are required",
            "sample_size": len(aligned_dates),
        }
    asset = np.asarray([portfolio_returns_by_date[day] for day in aligned_dates])
    benchmark = np.asarray([benchmark_returns[day] for day in aligned_dates])
    regression = regression_metrics(asset, benchmark, risk_free_rate=risk_free_rate)
    return {
        "available": True,
        "symbol": benchmark_symbol,
        "start_date": aligned_dates[0],
        "end_date": aligned_dates[-1],
        "sample_size": len(aligned_dates),
        "metrics": {**regression, **performance_ratios(asset, risk_free_rate=risk_free_rate, benchmark_returns=benchmark)},
        "market_arithmetic_expected_return": float(np.mean(benchmark) * 252),
    }


def _rolling_metrics(values: np.ndarray, window: int = 60) -> list[dict[str, float | int]]:
    if values.size < window:
        return []
    output = []
    for end in range(window, values.size + 1):
        sample = values[end - window:end]
        output.append({
            "observation": end,
            "annualized_volatility": float(np.std(sample, ddof=1) * np.sqrt(252)),
        })
    return output


def portfolio_quant(db: Session, user: User, portfolio_id: str, shrinkage: float = 0.20):
    portfolio = get_portfolio_or_404(db, user, portfolio_id)
    symbols, days, prices = _aligned_prices(db, portfolio.id, None, None)
    returns = return_matrix(prices)
    covariance = covariance_matrix(returns, shrinkage)
    correlation = correlation_matrix(returns)
    summary = get_portfolio_summary(db, user, portfolio_id)
    market_values = {row.symbol: float(row.market_value) for row in summary.holdings}
    total = float(summary.total_value)
    weights = np.array([market_values[s] / total for s in symbols]) if total else np.full(len(symbols), 1 / len(symbols))
    cash_weight = float(summary.cash_balance) / total if total else 0.0
    performance = get_portfolio_performance(db, user, portfolio.id, limit=5000)
    portfolio_returns_by_date = {
        point.value_date: float(point.day_change_percent) / 100
        for point in performance
        if point.day_change_percent is not None
    }
    portfolio_returns = np.asarray(list(portfolio_returns_by_date.values()))
    if len(portfolio_returns) >= 30:
        metrics: dict[str, object] = risk_metrics(portfolio_returns).to_dict()
        metrics["history_method"] = "ledger_time_weighted_return"
    else:
        metrics = {"available": False, "reason": "At least 30 cash-flow-adjusted ledger return observations are required", "sample_size": len(portfolio_returns)}
    metrics["concentration_hhi"] = float(weights @ weights + cash_weight**2)
    metrics["variance"] = float(weights @ covariance @ weights)
    metrics["cash_weight"] = cash_weight
    metrics["risk_model_cash_assumption"] = "Cash has zero covariance; observed ledger returns remain the performance basis."
    metrics["return_basis"] = "ledger_time_weighted_price_and_recorded_cash_income"
    # Corporate-action coverage is not yet complete enough to make an adjusted
    # total-return claim. Recorded ledger actions are honored, but absence is not
    # treated as evidence that no action occurred.
    recorded_actions = db.scalar(select(func.count()).select_from(CorporateAction)) or 0
    metrics["total_return_available"] = False
    metrics["total_return_unavailable_reason"] = (
        "Corporate-action source coverage is not certified complete; metrics include only recorded ledger actions and cash income."
    )
    metrics["recorded_corporate_action_count"] = int(recorded_actions)
    constraints = _selected_ips_constraints(db, portfolio)
    benchmark_symbol = _benchmark_symbol(db, portfolio, constraints)
    risk_free = _effective_risk_free_rate(db, days[-1], str(constraints.get("risk_free_series_key")) if constraints.get("risk_free_series_key") else None)
    benchmark = None
    if benchmark_symbol and risk_free:
        benchmark = _benchmark_analysis(db, benchmark_symbol, portfolio_returns_by_date, float(risk_free["annual_rate"]))
        benchmark["risk_free"] = risk_free
    elif benchmark_symbol:
        benchmark = {"available": False, "symbol": benchmark_symbol, "reason": "No effective-dated observed risk-free series is available"}
    else:
        benchmark = {"available": False, "reason": "No benchmark is configured in the confirmed IPS or portfolio"}
    contributions = risk_contributions(weights, covariance)
    fingerprint_data = {
        "portfolio_id": portfolio.id,
        "holding_version": [(row.symbol, str(row.quantity), str(row.average_cost)) for row in summary.holdings],
        "performance_tail": [(day.isoformat(), value) for day, value in list(portfolio_returns_by_date.items())[-10:]],
        "performance_count": len(portfolio_returns_by_date),
        "cash_balance": str(summary.cash_balance),
        "data_cutoff": days[-1].isoformat(),
        "benchmark": benchmark,
        "shrinkage": shrinkage,
        "history_start": portfolio.history_start.isoformat() if portfolio.history_start else None,
    }
    fingerprint = sha256(_json(fingerprint_data).encode()).hexdigest()
    run = db.scalar(select(AnalysisRun).where(AnalysisRun.input_fingerprint == fingerprint))
    result_data = {"data_cutoff": days[-1].isoformat(), "symbols": symbols, "sample_size": len(days) - 1, "annualization": 252, "covariance_shrinkage": shrinkage, "portfolio": metrics, "benchmark": benchmark, "rolling": {"window": 60, "portfolio_volatility": _rolling_metrics(portfolio_returns)}, "covariance": covariance.tolist(), "correlation": correlation.tolist(), "risk_contributions": dict(zip(symbols, [float(value) for value in contributions["percentage"]], strict=True)), "warnings": [] if portfolio.history_complete else ["Performance before the migration/opening-balance baseline is unavailable."]}
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
    estimate = None
    capm_inputs = None
    constraints = _selected_ips_constraints(db, portfolio)
    if payload.expected_return_method == "capm":
        benchmark_symbol, proxy_diagnostics = _capm_market_proxy_symbol(db, constraints)
        if payload.benchmark_symbol and payload.benchmark_symbol.upper() != benchmark_symbol:
            raise HTTPException(status_code=422, detail={"code": "invalid_capm_proxy_override", "message": "CAPM uses the approved market proxy from the IPS, not the performance benchmark.", "diagnostics": proxy_diagnostics})
        if not benchmark_symbol:
            raise HTTPException(status_code=422, detail={"code": "capm_market_proxy_unavailable", "message": "CAPM requires an approved broad-index market proxy", "diagnostics": proxy_diagnostics})
        benchmark_by_date = {row.trade_date: float(row.close) for row in price_series(db, benchmark_symbol, payload.start_date, payload.end_date)}
        selected_indexes = [index for index, day in enumerate(days) if day in benchmark_by_date]
        if len(selected_indexes) < 31:
            raise HTTPException(status_code=422, detail="CAPM requires at least 31 dates aligned across holdings and benchmark")
        days = [days[index] for index in selected_indexes]
        prices = [[column[index] for index in selected_indexes] for column in prices]
        returns = return_matrix(prices)
        benchmark_prices = np.asarray([benchmark_by_date[day] for day in days])
        market_returns = benchmark_prices[1:] / benchmark_prices[:-1] - 1
        risk_free = _effective_risk_free_rate(db, days[-1], payload.risk_free_series_key)
        if risk_free is None:
            raise HTTPException(status_code=422, detail="CAPM requires an effective-dated observed risk-free series")
        estimate = estimate_expected_returns(
            "capm",
            returns,
            market_returns=market_returns,
            risk_free_rate=float(risk_free["annual_rate"]),
        )
        capm_inputs = {"capm_market_proxy_symbol": benchmark_symbol, "risk_free": risk_free, "diagnostics": proxy_diagnostics}
    if payload.expected_return_method:
        if payload.expected_return_method != "capm":
            try:
                assumptions = [payload.expected_return_assumptions[s] for s in symbols] if payload.expected_return_method == "user_model" else None
            except KeyError as exc:
                raise HTTPException(status_code=422, detail=f"Missing expected-return assumption for {exc.args[0]}") from exc
            estimate = estimate_expected_returns(payload.expected_return_method, returns, assumptions=assumptions, shrinkage=payload.expected_return_shrinkage)
    ips_version = db.get(PortfolioIPSVersion, portfolio.selected_ips_version_id) if portfolio.selected_ips_version_id else None
    constraints = _load(ips_version.constraints_json) if ips_version else constraints
    informational = {"goal", "benchmark_symbol", "performance_benchmark_symbol", "capm_market_proxy_symbol", "risk_free_series_key", "operational_cash_return", "operational_cash_return_basis", "operational_cash_return_effective_date", "long_only", "loss_budget", "horizon_years", "notes", "risk_capacity", "risk_willingness", "overall_risk_tolerance", "risk_budget_tolerance", "profile_policy_note", "tax_notes", "required_return_method", "objective_inputs"}
    supported = {
        "max_instrument_weight", "excluded_instruments", "allowed_instruments", "min_cash_weight", "max_cash_weight",
        "max_sector_weight", "allowed_asset_types", "allowed_currencies", "shariah_only",
        "minimum_daily_volume", "target_volatility", "target_beta", "risk_budgets",
        "leverage_allowed", "derivatives_allowed", "liquidity_requirement",
    }
    unsupported = sorted(set(constraints) - informational - supported)
    if unsupported:
        raise HTTPException(status_code=422, detail={"message": "IPS contains constraints that cannot be represented by this optimizer", "unsupported_constraints": unsupported})
    instruments_by_symbol = {item.symbol: item for item in db.scalars(select(Instrument).where(Instrument.symbol.in_(symbols)))}
    lower = [payload.minimum_weight] * len(symbols)
    upper = [payload.maximum_weight] * len(symbols)
    excluded = {str(value).upper() for value in constraints.get("excluded_instruments", [])}
    allowed = {str(value).upper() for value in constraints.get("allowed_instruments", [])}
    allowed_types = {str(value).lower() for value in constraints.get("allowed_asset_types", [])}
    allowed_currencies = {str(value).upper() for value in constraints.get("allowed_currencies", [])}
    minimum_volume = float(constraints.get("minimum_daily_volume", 0) or 0)
    for index, symbol in enumerate(symbols):
        if symbol in excluded or (allowed and symbol not in allowed): upper[index] = 0
        if "max_instrument_weight" in constraints: upper[index] = min(upper[index], float(constraints["max_instrument_weight"]))
        instrument = instruments_by_symbol.get(symbol)
        metadata = _load(instrument.metadata_json) if instrument else {}
        if instrument and allowed_types and instrument.instrument_type.lower() not in allowed_types: upper[index] = 0
        if instrument and allowed_currencies and instrument.currency.upper() not in allowed_currencies: upper[index] = 0
        if instrument and constraints.get("derivatives_allowed") is False and instrument.instrument_type.lower() in {"derivative", "future", "option"}: upper[index] = 0
        if constraints.get("shariah_only") and metadata.get("shariah_compliant") is not True: upper[index] = 0
        observed = latest_price(db, symbol)
        if minimum_volume and (observed is None or observed.volume < minimum_volume): upper[index] = 0
    include_cash = payload.include_cash or payload.maximum_cash_weight is not None or "max_cash_weight" in constraints or float(payload.minimum_cash_weight or 0) > 0 or float(constraints.get("min_cash_weight", 0) or 0) > 0 or float(constraints.get("liquidity_requirement", 0) or 0) > 0
    portfolio_value = float(get_portfolio_summary(db, user, portfolio.id).total_value)
    liquidity_weight = float(constraints.get("liquidity_requirement", 0) or 0) / portfolio_value if portfolio_value else 0
    cash_minimum = max(float(payload.minimum_cash_weight or 0), float(constraints.get("min_cash_weight", 0) or 0), liquidity_weight)
    cash_maximum = float(payload.maximum_cash_weight if payload.maximum_cash_weight is not None else constraints.get("max_cash_weight", DEFAULT_MAX_CASH_WEIGHT))
    if cash_minimum > cash_maximum + WEIGHT_TOLERANCE:
        raise HTTPException(status_code=422, detail={"code": "cash_bounds_infeasible", "message": "Minimum cash exceeds maximum cash", "binding_constraints": ["min_cash_weight", "max_cash_weight"], "minimum_cash_weight": cash_minimum, "maximum_cash_weight": cash_maximum})
    if payload.objective in {"risk_parity", "risk_budget"} and payload.minimum_cash_weight is None and "min_cash_weight" not in constraints:
        raise HTTPException(status_code=422, detail={"code": "cash_minimum_required", "message": "Risk-parity and risk-budget objectives require a confirmed cash minimum so the risky sleeve is explicit.", "binding_constraints": ["min_cash_weight"]})
    observed_risk_free = _effective_risk_free_rate(db, days[-1], payload.risk_free_series_key)
    effective_risk_free = float(capm_inputs["risk_free"]["annual_rate"]) if capm_inputs else payload.risk_free_rate if payload.risk_free_rate is not None else float(observed_risk_free["annual_rate"]) if observed_risk_free else None
    if payload.objective == "max_sharpe" and effective_risk_free is None:
        raise HTTPException(status_code=422, detail="Maximum Sharpe optimization requires an explicit or observed T-bill/government risk-free rate.")
    if include_cash:
        symbols.append("CASH")
        returns = np.column_stack([returns, np.zeros(returns.shape[0])])
        lower.append(cash_minimum)
        upper.append(cash_maximum)
        if estimate:
            cash_return = payload.cash_return_rate
            estimate = type(estimate)(estimate.method, np.append(estimate.values, cash_return), {**estimate.assumptions, "cash_return_assumption": cash_return})
    covariance = covariance_matrix(returns, payload.covariance_shrinkage)
    linear_upper_bounds = []
    if "max_sector_weight" in constraints:
        sector_cap = float(constraints["max_sector_weight"])
        sectors = sorted({instrument.sector or "Unknown" for instrument in instruments_by_symbol.values()})
        for sector in sectors:
            coefficients = np.asarray([
                1.0 if symbol in instruments_by_symbol and (instruments_by_symbol[symbol].sector or "Unknown") == sector else 0.0
                for symbol in symbols
            ])
            linear_upper_bounds.append((coefficients, sector_cap, f"sector:{sector}"))
    try:
        betas = np.array([payload.beta_assumptions[s] for s in symbols if s != "CASH"]) if payload.beta_assumptions else None
    except KeyError as exc:
        raise HTTPException(status_code=422, detail=f"Missing beta assumption for {exc.args[0]}") from exc
    if betas is None and estimate and estimate.method == "capm":
        betas = np.asarray(estimate.assumptions["betas"], dtype=float)
    if payload.objective == "target_beta" and betas is None:
        proxy_symbol, proxy_diagnostics = _capm_market_proxy_symbol(db, constraints)
        benchmark_returns = _benchmark_returns_for_optimizer(db, proxy_symbol, days)
        if benchmark_returns is None:
            raise HTTPException(status_code=422, detail={"code": "beta_inputs_unavailable", "message": "Target beta requires aligned returns for an approved CAPM market proxy.", "diagnostics": proxy_diagnostics})
        variance = float(np.var(benchmark_returns, ddof=1))
        if variance <= 0:
            raise HTTPException(status_code=422, detail={"code": "degenerate_market_proxy", "message": "The approved CAPM market proxy has zero return variance."})
        risky_returns = returns[:, :len(symbols) - (1 if include_cash else 0)]
        betas = np.asarray([np.cov(risky_returns[:, index], benchmark_returns, ddof=1)[0, 1] / variance for index in range(risky_returns.shape[1])])
    if include_cash and betas is not None:
        betas = np.append(betas, 0.0)
    configured_budgets = payload.risk_budgets or constraints.get("risk_budgets")
    try:
        budgets = np.array([configured_budgets[s] for s in symbols if s != "CASH"]) if configured_budgets else None
    except KeyError as exc:
        raise HTTPException(status_code=422, detail=f"Missing risk budget for {exc.args[0]}") from exc
    target_return = payload.target_return
    if payload.objective == "target_return_minimum_variance" and target_return is None and ips_version and ips_version.required_return is not None:
        target_return = float(ips_version.required_return)
    target_volatility = None
    if payload.objective == "target_volatility_maximum_return":
        target_volatility = payload.target_volatility if payload.target_volatility is not None else (float(constraints["target_volatility"]) if "target_volatility" in constraints else None)
    target_beta = None
    if payload.objective == "target_beta":
        target_beta = payload.target_beta if payload.target_beta is not None else (float(constraints["target_beta"]) if "target_beta" in constraints else None)
    try:
        if payload.objective in {"risk_parity", "risk_budget"} and include_cash:
            risky_share = 1.0 - cash_minimum
            if risky_share <= WEIGHT_TOLERANCE:
                raise ValueError("Risk-budget objectives require a positive risky sleeve")
            risky_count = len(symbols) - 1
            risky_covariance = covariance[:risky_count, :risky_count]
            risky_lower = [value / risky_share for value in lower[:risky_count]]
            risky_upper = [min(1.0, value / risky_share) for value in upper[:risky_count]]
            risky_budgets = budgets[:risky_count] if budgets is not None else None
            risky_result = optimize(risky_covariance, objective=payload.objective, risk_budgets=risky_budgets, lower_bounds=risky_lower, upper_bounds=risky_upper)
            if risky_result.status == "optimal":
                total_weights = [weight * risky_share for weight in risky_result.weights] + [cash_minimum]
                result = type(risky_result)("optimal", total_weights, float(np.asarray(total_weights) @ estimate.values) if estimate is not None else None, float(risky_result.volatility or 0) * risky_share, {**risky_result.diagnostics, "portfolio_basis": "risky_sleeve", "attached_cash_weight": cash_minimum})
            else:
                result = risky_result
        else:
            result = optimize(
            covariance, objective=payload.objective, expected_returns=estimate.values if estimate else None,
            target_return=target_return, target_volatility=target_volatility,
            target_beta=target_beta, betas=betas, risk_budgets=budgets,
            risk_free_rate=effective_risk_free,
            lower_bounds=lower, upper_bounds=upper, linear_upper_bounds=linear_upper_bounds,
            )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"message": str(exc), "lower_bound_sum": sum(lower), "upper_bound_sum": sum(upper), "nearest_relaxations": ["Reduce minimum weights or cash", "Increase maximum instrument/sector weights", "Remove exclusions"]}) from exc
    assumptions_data = {"covariance": "diagonal_shrinkage", "covariance_shrinkage": payload.covariance_shrinkage, "expected_returns": estimate.assumptions if estimate else None, "capm_inputs": capm_inputs, "annualization": 252, "cash": {"instrument": "operational_cash", "annual_return": payload.cash_return_rate, "basis": payload.cash_return_basis, "effective_date": payload.cash_return_effective_date.isoformat() if payload.cash_return_effective_date else days[-1].isoformat(), "minimum_weight": cash_minimum, "maximum_weight": cash_maximum, "maximum_source": "request_or_ips" if payload.maximum_cash_weight is not None or "max_cash_weight" in constraints else "product_default"}}
    result_data = result.to_dict()
    row = OptimizerRun(portfolio_id=portfolio.id, objective=payload.objective, expected_return_method=payload.expected_return_method, ips_version_id=ips_version.id if ips_version else None, data_cutoff=days[-1], bounds_json=_json({"lower": lower, "upper": upper}), solver=str(result.diagnostics.get("solver")) if result.diagnostics.get("solver") else None, seed=0, input_json=_json(payload.model_dump(mode="json")), result_json=_json({**result_data, "symbols": symbols}), status=result.status, diagnostics_json=_json(result.diagnostics))
    db.add(row); db.flush()
    proposal = None
    if result.status == "optimal":
        instruments = instruments_by_symbol
        proposal_version = (db.scalar(select(func.max(AllocationSet.version)).where(AllocationSet.portfolio_id == portfolio.id, AllocationSet.kind == "optimized")) or 0) + 1
        proposal = AllocationSet(portfolio_id=portfolio.id, kind="optimized", version=proposal_version, status="proposal", assumptions_json=_json(assumptions_data), base_value=Decimal(str(get_portfolio_summary(db, user, portfolio.id).total_value)), created_by_user_id=user.id)
        db.add(proposal); db.flush()
        for symbol, weight in zip(symbols, result.weights, strict=True):
            if symbol == "CASH":
                db.add(AllocationItem(allocation_set_id=proposal.id, symbol="CASH", instrument_id=None, is_cash=True, target_weight=Decimal(str(weight)), locked=False))
            elif symbol in instruments:
                db.add(OptimizerAllocation(optimizer_run_id=row.id, instrument_id=instruments[symbol].id, weight=Decimal(str(weight))))
                db.add(AllocationItem(allocation_set_id=proposal.id, symbol=symbol, instrument_id=instruments[symbol].id, is_cash=False, target_weight=Decimal(str(weight)), locked=False))
    record_event(
        db, user, event_type="optimizer_run", entity_type="optimizer_run", entity_id=row.id, portfolio_id=portfolio.id,
        data_cutoff=days[-1],
        new_state={"objective": payload.objective, "expected_return_method": payload.expected_return_method, "status": result.status, "assumptions": assumptions_data, "allocation_set_id": proposal.id if proposal else None},
        note="Expected-return/covariance assumption inputs for this run are recorded in new_state.assumptions.",
    )
    db.commit(); db.refresh(row)
    return {"id": row.id, "status": result.status, "objective": payload.objective, "expected_return_method": payload.expected_return_method, "data_cutoff": days[-1], "symbols": symbols, "weights": dict(zip(symbols, result.weights, strict=True)) if result.weights else {}, "expected_return": result.expected_return, "volatility": result.volatility, "diagnostics": result.diagnostics, "assumptions": assumptions_data, "allocation_set_id": proposal.id if proposal else None}


def security_quant(db: Session, instrument_id: str):
    instrument = db.get(Instrument, instrument_id)
    if instrument is None:
        raise HTTPException(status_code=404, detail="Instrument not found")
    rows = price_series(db, instrument.symbol)
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
    current_quantities = {holding.symbol: float(holding.quantity) for holding in summary.holdings}
    targets = {symbol.upper(): weight for symbol, weight in payload.target_weights.items()}
    for symbol in current:
        targets.setdefault(symbol, 0.0)
    trades = []
    residual_cash = float(summary.cash_balance)
    warnings = []
    locked = {symbol.upper() for symbol in payload.locked_symbols}
    for symbol, weight in targets.items():
        if symbol == "CASH":
            continue
        instrument = db.scalar(select(Instrument).where(Instrument.symbol == symbol.upper()))
        price = latest_price(db, symbol.upper())
        if instrument is None or price is None:
            warnings.append(f"{symbol.upper()}: missing instrument or current price")
            continue
        target_amount = total * weight
        difference = target_amount - current.get(symbol.upper(), 0)
        if symbol in locked and abs(difference) >= payload.minimum_trade_value:
            warnings.append(f"{symbol}: locked position was not traded")
            continue
        if difference < 0 and not payload.allow_sells:
            warnings.append(f"{symbol}: sell required but sells are disabled")
            continue
        if abs(difference) < payload.minimum_trade_value:
            continue
        metadata = _load(instrument.metadata_json)
        lot_size = float(metadata.get("lot_size", 1) or 1)
        quantity = np.floor(abs(difference) / float(price.close) / lot_size) * lot_size
        if quantity <= 0:
            warnings.append(f"{symbol}: target difference is below one tradable lot")
            continue
        gross = quantity * float(price.close)
        fee = gross * payload.fee_rate
        tax = gross * payload.tax_rate if difference < 0 else 0.0
        side = "buy" if difference > 0 else "sell"
        if side == "sell" and quantity > current_quantities.get(symbol, 0):
            quantity = current_quantities.get(symbol, 0)
            gross = quantity * float(price.close); fee = gross * payload.fee_rate; tax = gross * payload.tax_rate
        residual_cash += (-gross - fee) if side == "buy" else (gross - fee - tax)
        trades.append({"symbol": symbol.upper(), "side": side, "quantity": float(quantity), "price": float(price.close), "gross_amount": gross, "estimated_fee": fee, "estimated_tax": tax, "before_weight": current.get(symbol.upper(), 0) / total if total else 0, "target_weight": weight})
    if residual_cash < -1e-6:
        warnings.append("Proposed buys exceed available cash after estimated fees.")
    projected = dict(current)
    for trade in trades:
        projected[trade["symbol"]] = projected.get(trade["symbol"], 0) + (trade["gross_amount"] if trade["side"] == "buy" else -trade["gross_amount"])
    projected_total = residual_cash + sum(max(value, 0) for value in projected.values())
    projected_weights = {symbol: max(value, 0) / projected_total if projected_total else 0 for symbol, value in projected.items()}
    projected_weights["CASH"] = residual_cash / projected_total if projected_total else 0
    constraints = _selected_ips_constraints(db, portfolio)
    violations = []
    if "min_cash_weight" in constraints and projected_weights["CASH"] + 1e-8 < float(constraints["min_cash_weight"]):
        violations.append({"code": "min_cash_weight", "actual": projected_weights["CASH"], "limit": float(constraints["min_cash_weight"])})
    if "max_instrument_weight" in constraints:
        limit = float(constraints["max_instrument_weight"])
        violations.extend({"code": "max_instrument_weight", "symbol": symbol, "actual": weight, "limit": limit} for symbol, weight in projected_weights.items() if symbol != "CASH" and weight > limit + 1e-8)
    excluded = {str(value).upper() for value in constraints.get("excluded_instruments", [])}
    violations.extend({"code": "instrument_not_allowed", "symbol": symbol} for symbol, weight in projected_weights.items() if symbol in excluded and weight > 1e-8)
    risk_impact: dict[str, object] = {"available": False, "reason": "Aligned covariance is unavailable."}
    try:
        quant = portfolio_quant(db, user, portfolio.id)
        quant_symbols = quant["symbols"]
        if all(symbol in projected_weights for symbol in quant_symbols):
            covariance = np.asarray(quant["covariance"], dtype=float)
            risky_target = np.asarray([projected_weights[symbol] for symbol in quant_symbols])
            before_volatility = float(np.sqrt(float(quant["portfolio"]["variance"])))
            after_volatility = float(np.sqrt(max(risky_target @ covariance @ risky_target, 0)))
            risk_impact = {"available": True, "before_annualized_volatility": before_volatility, "after_annualized_volatility": after_volatility, "change": after_volatility - before_volatility, "method": "same_covariance_post_rounding_weights"}
    except (HTTPException, ValueError, KeyError):
        pass
    post_validation = {"valid": residual_cash >= -1e-6 and not violations, "projected_weights": projected_weights, "violations": violations, "fees_and_taxes_included": True, "lot_sizes_applied": True, "locked_positions_checked": True, "sell_rules_checked": True}
    return {"portfolio_id": portfolio.id, "data_cutoff": summary.data_freshness_date, "trades": trades, "residual_cash": residual_cash, "warnings": warnings, "post_trade_validation": post_validation, "risk_impact": risk_impact}


def run_scenario(db: Session, user: User, portfolio_id: str, payload: ScenarioRequest):
    portfolio = get_portfolio_or_404(db, user, portfolio_id)
    summary = get_portfolio_summary(db, user, portfolio_id)
    positions, pnl = [], 0.0
    sector_contributions: dict[str, float] = {}
    for holding in summary.holdings:
        value = float(holding.market_value)
        instrument = db.scalar(select(Instrument).where(Instrument.symbol == holding.symbol))
        shock, mapping_sources = resolve_shock(instrument, {key.upper(): value for key, value in payload.shocks.items()}, payload.sector_shocks, payload.factor_shocks) if instrument else (payload.shocks.get(holding.symbol, 0.0), [])
        position_pnl = value * shock; pnl += position_pnl
        sector = holding.sector or "Unknown"
        sector_contributions[sector] = sector_contributions.get(sector, 0.0) + position_pnl
        positions.append({"symbol": holding.symbol, "sector": holding.sector, "value": value, "shock": shock, "pnl": position_pnl, "mapping_sources": mapping_sources})
    total = float(summary.total_value); cutoff = summary.data_freshness_date or date.today()
    stressed_total = total + pnl
    stressed_weights = {
        row["symbol"]: (float(row["value"]) + float(row["pnl"])) / stressed_total if stressed_total else 0.0
        for row in positions
    }
    stressed_weights["CASH"] = float(summary.cash_balance) / stressed_total if stressed_total else 0.0
    constraints = _selected_ips_constraints(db, portfolio)
    sector_by_symbol = {holding.symbol: holding.sector for holding in summary.holdings}
    modeled_inputs: dict[str, object] = {"liquid_assets": float(summary.cash_balance), "data_cutoff": cutoff, "estimator": "stressed_weight_aligned_price_covariance_v1"}
    try:
        model_symbols, model_days, model_prices = _aligned_prices(db, portfolio.id, None, None)
        model_returns = return_matrix(model_prices)
        model_covariance = covariance_matrix(model_returns, 0.20)
        model_weights = np.asarray([stressed_weights.get(symbol, 0.0) for symbol in model_symbols])
        modeled_inputs["portfolio_volatility"] = float(np.sqrt(max(model_weights @ model_covariance @ model_weights, 0)))
        modeled_inputs["risk_contributions"] = dict(zip(model_symbols, [float(value) for value in risk_contributions(model_weights, model_covariance)["percentage"]], strict=True))
        benchmark_symbol = _benchmark_symbol(db, portfolio, constraints)
        risk_free = _effective_risk_free_rate(db, model_days[-1], str(constraints.get("risk_free_series_key")) if constraints.get("risk_free_series_key") else None)
        if benchmark_symbol and risk_free:
            modeled_returns = model_returns @ model_weights
            benchmark_analysis = _benchmark_analysis(db, benchmark_symbol, dict(zip(model_days[1:], modeled_returns.tolist(), strict=True)), float(risk_free["annual_rate"]))
            if benchmark_analysis.get("available"):
                modeled_inputs["portfolio_beta"] = benchmark_analysis.get("metrics", {}).get("beta")
    except HTTPException:
        pass
    compliance = evaluate_ips_constraints(
        constraints,
        [{"symbol": symbol, "weight": weight, "sector": "Cash" if symbol == "CASH" else sector_by_symbol.get(symbol)} for symbol, weight in stressed_weights.items()],
        ips_version_id=portfolio.selected_ips_version_id,
        valuation_complete=summary.valuation_complete,
        unpriced_symbols=summary.unpriced_symbols,
        context="stressed",
        modeled_inputs=modeled_inputs,
    )
    compliance["stressed_weights"] = stressed_weights
    assumptions = ["Direct instrument shocks override sector/factor mappings to avoid double counting.", "Sector and factor shocks are additive when no direct shock exists.", "Cash is held constant under the configured shocks.", "No liquidity, tax, fee, or second-order effects are modeled."]
    unmapped = [str(position["symbol"]) for position in positions if not position["mapping_sources"] and (payload.sector_shocks or payload.factor_shocks)]
    if unmapped:
        assumptions.append(f"Missing mapping diagnostics: {', '.join(unmapped)} received no sector or factor mapping and therefore a zero shock.")
    result = {"portfolio_value": total, "stressed_portfolio_value": stressed_total, "pnl": pnl, "pnl_percent": pnl / total if total else 0, "positions": positions, "sector_contributions": sector_contributions, "compliance": compliance, "assumptions": assumptions}
    all_shocks = {"instruments": payload.shocks, "sectors": payload.sector_shocks, "factors": payload.factor_shocks}
    row = ScenarioRun(portfolio_id=portfolio.id, name=payload.name, shocks_json=_json(all_shocks), result_json=_json(result), data_cutoff=cutoff, assumptions_json=_json({"scenario_type": payload.scenario_type, "mapping_order": ["instrument", "sector", "factor"]}), status="completed")
    db.add(row); db.flush()
    record_event(
        db, user, event_type="scenario_run", entity_type="scenario_run", entity_id=row.id, portfolio_id=portfolio.id,
        data_cutoff=cutoff,
        new_state={"name": row.name, "scenario_type": payload.scenario_type, "pnl": pnl, "compliance_status": compliance.get("status")},
        note="Deterministic shocks applied; see shocks_json on the run for the full input.",
    )
    db.commit(); db.refresh(row)
    return {"id": row.id, "name": row.name, "data_cutoff": cutoff, "shocks": payload.shocks, **result}


def create_monitoring_rule(db: Session, user: User, portfolio_id: str, rule_type: str, threshold: dict, deduplication_window_minutes: int = 1440):
    portfolio = get_portfolio_or_404(db, user, portfolio_id)
    row = MonitoringRule(user_id=user.id, portfolio_id=portfolio.id, rule_type=rule_type, threshold_json=_json(threshold), deduplication_window_minutes=deduplication_window_minutes)
    db.add(row); db.commit(); db.refresh(row)
    return {"id": row.id, "portfolio_id": row.portfolio_id, "rule_type": row.rule_type, "threshold": threshold, "enabled": row.enabled, "deduplication_window_minutes": row.deduplication_window_minutes}


def list_recommendations(db: Session, user: User):
    rows = db.scalars(select(Recommendation).where(Recommendation.user_id == user.id).order_by(Recommendation.created_at.desc())).all()
    allocations = db.scalars(select(AllocationSet).where(AllocationSet.created_by_user_id == user.id).order_by(AllocationSet.created_at.desc())).all()
    linked_allocations: dict[str, AllocationSet] = {}
    for allocation in allocations:
        recommendation_id = _load(allocation.assumptions_json).get("recommendation_id")
        if recommendation_id and str(recommendation_id) not in linked_allocations:
            linked_allocations[str(recommendation_id)] = allocation
    results = []
    for row in rows:
        evidence = _load(row.evidence_json)
        assumptions = _load(row.assumptions_json)
        rule_type = str(evidence.get("rule_type") or assumptions.get("rule_type") or "portfolio signal")
        if rule_type in {"concentration", "position_weight"} and evidence.get("classification") is None:
            portfolio = get_portfolio_or_404(db, user, row.portfolio_id)
            version = db.get(PortfolioIPSVersion, portfolio.selected_ips_version_id) if portfolio.selected_ips_version_id else None
            constraints = _load(version.constraints_json) if version else {}
            current_value = max((float(item["weight"]) for item in evidence.get("breaches", []) if item.get("weight") is not None), default=None)
            ips_limit = constraints.get("max_instrument_weight")
            evidence.update({"rule_type": rule_type, "rule_threshold": assumptions.get("threshold", {"maximum": evidence.get("limit")}), "current_value": current_value, "related_ips_limit": ips_limit, "ips_version_id": version.id if version else None, "classification": "mandate_breach" if current_value is not None and ips_limit is not None and current_value > float(ips_limit) else "monitoring_warning"})
        trigger_label = "IPS mandate breach" if row.trigger.startswith("ips:") else rule_type.replace("_", " ").title()
        linked = linked_allocations.get(row.id)
        results.append({
            "id": row.id,
            "portfolio_id": row.portfolio_id,
            "trigger": row.trigger,
            "trigger_label": trigger_label,
            "evidence": evidence,
            "ips_violation": json.loads(row.ips_violation_json),
            "assumptions": assumptions,
            "expected_effect": _load(row.expected_effect_json),
            "uncertainty": _load(row.uncertainty_json),
            "freshness": _load(row.freshness_json),
            "message": row.message,
            "status": row.status,
            "linked_allocation": {"id": linked.id, "kind": linked.kind, "version": linked.version, "status": linked.status} if linked else None,
            "lifecycle": ["open", "reviewed", "resolved"],
            "links": {"monitoring": "/monitoring", "risk": f"/portfolios/{row.portfolio_id}/risk", "build": f"/portfolios/{row.portfolio_id}/build?recommendation={row.id}"},
            "created_at": row.created_at,
        })
    return results


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
    history = []
    for row in rows:
        result = _load(row.result_json)
        stored_shocks = _load(row.shocks_json)
        direct_shocks = stored_shocks.get("instruments", stored_shocks) if isinstance(stored_shocks, dict) else {}
        history.append(
            {
                "id": row.id,
                "name": row.name,
                "data_cutoff": row.data_cutoff,
                "shocks": direct_shocks,
                "portfolio_value": result.get("portfolio_value", 0.0),
                "stressed_portfolio_value": result.get(
                    "stressed_portfolio_value",
                    result.get("portfolio_value", 0.0) + result.get("pnl", 0.0),
                ),
                "pnl": result.get("pnl", 0.0),
                "pnl_percent": result.get("pnl_percent", 0.0),
                "positions": result.get("positions", []),
                "sector_contributions": result.get("sector_contributions", {}),
                "compliance": result.get("compliance", {}),
                "assumptions": result.get("assumptions", []),
            }
        )
    return history
