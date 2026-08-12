from __future__ import annotations

from datetime import date

import numpy as np
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.domain.quant import (
    correlation_matrix,
    covariance_matrix,
    estimate_expected_returns,
    optimize,
    return_matrix,
    risk_contributions,
    risk_metrics,
)
from app.domain.analytics_contract import CHANGE_TOLERANCE, WEIGHT_TOLERANCE, weight_diagnostics
from app.models.user import User
from app.models.workstation import PortfolioIPSVersion
from app.schemas.workstation import PortfolioComparisonRequest
from app.services.canonical_market_service import price_series
from app.services.compliance_service import evaluate_ips_constraints
from app.services.portfolio_service import get_portfolio_or_404, get_portfolio_summary
from app.services.workstation_service import (
    _aligned_prices,
    _benchmark_symbol,
    _capm_market_proxy_symbol,
    _effective_risk_free_rate,
    _load,
    _selected_ips_constraints,
    ips_compliance,
)


def _market_inputs(db: Session, user: User, portfolio_id: str):
    portfolio = get_portfolio_or_404(db, user, portfolio_id)
    symbols, days, prices = _aligned_prices(db, portfolio.id, None, None)
    returns = return_matrix(prices)
    covariance = covariance_matrix(returns, 0.20)
    expected = estimate_expected_returns("historical_shrunk", returns, shrinkage=0.50)
    constraints = _selected_ips_constraints(db, portfolio)
    benchmark_symbol = _benchmark_symbol(db, portfolio, constraints)
    risk_free = _effective_risk_free_rate(
        db,
        days[-1],
        str(constraints.get("risk_free_series_key")) if constraints.get("risk_free_series_key") else None,
    )
    return portfolio, symbols, days, returns, covariance, expected, constraints, benchmark_symbol, risk_free


def _benchmark_returns(db: Session, symbol: str | None, days: list[date]) -> np.ndarray | None:
    if not symbol:
        return None
    by_date = {row.trade_date: float(row.close) for row in price_series(db, symbol)}
    if any(day not in by_date for day in days):
        return None
    prices = np.asarray([by_date[day] for day in days], dtype=float)
    return prices[1:] / prices[:-1] - 1


def capital_market_assumptions(db: Session, user: User, portfolio_id: str):
    portfolio, symbols, days, returns, covariance, expected, constraints, benchmark_symbol, risk_free = _market_inputs(db, user, portfolio_id)
    capm_proxy_symbol, proxy_diagnostics = _capm_market_proxy_symbol(db, constraints)
    benchmark_returns = _benchmark_returns(db, capm_proxy_symbol, days)
    capm = None
    diagnostics: list[str] = []
    diagnostics.extend(proxy_diagnostics)
    if capm_proxy_symbol and benchmark_returns is None:
        diagnostics.append("CAPM market-proxy history is not aligned across the complete security sample.")
    if benchmark_returns is not None and risk_free:
        capm = estimate_expected_returns(
            "capm",
            returns,
            market_returns=benchmark_returns,
            risk_free_rate=float(risk_free["annual_rate"]),
        )
    elif not risk_free:
        diagnostics.append("CAPM assumptions are unavailable because no observed effective-dated risk-free input exists.")
    realized = np.mean(returns, axis=0) * 252
    volatility = np.std(returns, axis=0, ddof=1) * np.sqrt(252)
    securities = []
    for index, symbol in enumerate(symbols):
        securities.append({
            "symbol": symbol,
            "expected_return": float(expected.values[index]),
            "expected_return_method": expected.method,
            "volatility": float(volatility[index]),
            "beta": float(capm.assumptions["betas"][index]) if capm else None,
            "capm_return": float(capm.values[index]) if capm else None,
            "realized_return": float(realized[index]),
            "diagnostics": [] if capm else ["CAPM lens unavailable; historical and shrunk estimates remain distinct."],
        })
    provenance = []
    for symbol in symbols:
        rows = price_series(db, symbol)
        last = rows[-1]
        provenance.append({
            "symbol": symbol,
            "source": last.source,
            "source_url": last.source_url,
            "artifact_id": last.artifact_id,
            "effective_date": last.trade_date,
        })
    return {
        "portfolio_id": portfolio.id,
        "data_cutoff": days[-1],
        "sample_start": days[0],
        "sample_size": len(days) - 1,
        "annualization": 252,
        "estimator": {
            "expected_return_method": "historical_shrunk",
            "expected_return_shrinkage": 0.50,
            "covariance_method": "diagonal_shrinkage",
            "covariance_shrinkage": 0.20,
            "note": "Historical estimates are an explicit modeling lens, not a forecast claim.",
        },
        "risk_free": risk_free,
        "benchmark": {
            "symbol": capm_proxy_symbol,
            "performance_benchmark_symbol": benchmark_symbol,
            "role": "capm_market_proxy",
            "available": benchmark_returns is not None,
            "realized_return": float(np.mean(benchmark_returns) * 252) if benchmark_returns is not None else None,
        },
        "securities": securities,
        "covariance": covariance.tolist(),
        "correlation": correlation_matrix(returns).tolist(),
        "provenance": provenance,
        "warnings": diagnostics,
    }


def efficient_frontier_analysis(db: Session, user: User, portfolio_id: str, points: int = 24):
    portfolio, symbols, days, returns, covariance, expected, constraints, _benchmark, risk_free = _market_inputs(db, user, portfolio_id)
    maximum = float(constraints.get("max_instrument_weight", 1.0))
    upper = [maximum] * len(symbols)
    frontier = []
    for target in np.linspace(float(np.min(expected.values)), float(np.max(expected.values)), points):
        result = optimize(
            covariance,
            objective="target_return_minimum_variance",
            expected_returns=expected.values,
            target_return=float(target),
            upper_bounds=upper,
        )
        if result.status == "optimal" and result.expected_return is not None and result.volatility is not None:
            frontier.append({
                "expected_return": result.expected_return,
                "volatility": result.volatility,
                "weights": dict(zip(symbols, result.weights, strict=True)),
            })
    minimum = optimize(covariance, objective="minimum_variance", expected_returns=expected.values, upper_bounds=upper)
    maximum_sharpe = optimize(
        covariance,
        objective="max_sharpe",
        expected_returns=expected.values,
        risk_free_rate=float(risk_free["annual_rate"]),
        upper_bounds=upper,
    ) if risk_free else None
    summary = get_portfolio_summary(db, user, portfolio.id)
    market_values = {row.symbol: float(row.market_value) for row in summary.holdings}
    risky_total = sum(market_values.values())
    current_weights = np.asarray([market_values.get(symbol, 0) / risky_total for symbol in symbols])

    def point(weights: np.ndarray | list[float] | None):
        if weights is None or len(weights) == 0:
            return None
        values = np.asarray(weights, dtype=float)
        return {
            "expected_return": float(values @ expected.values),
            "volatility": float(np.sqrt(max(values @ covariance @ values, 0))),
            "weights": dict(zip(symbols, values.tolist(), strict=True)),
        }

    chart_values = [(item["volatility"], item["expected_return"]) for item in frontier]
    if any(not np.isfinite(volatility) or not np.isfinite(expected_return) or volatility < 0 or volatility > 5 or abs(expected_return) > 5 for volatility, expected_return in chart_values):
        raise HTTPException(status_code=422, detail={"code": "frontier_unit_contract_error", "message": "Frontier values must be finite annual decimals within validated chart ranges.", "unit": "decimal"})

    return {
        "portfolio_id": portfolio.id,
        "data_cutoff": days[-1],
        "estimator": "historical_shrunk_comparison",
        "unit": "decimal",
        "portfolio_basis": "risky_sleeve",
        "feasible_set_label": "Unconstrained risky-sleeve comparison",
        "points": frontier,
        "markers": {
            "current": point(current_weights),
            "global_minimum_variance": point(minimum.weights if minimum.status == "optimal" else None),
            "maximum_sharpe": point(maximum_sharpe.weights if maximum_sharpe and maximum_sharpe.status == "optimal" else None),
        },
        "assumptions": {
            "long_only": True,
            "maximum_instrument_weight": maximum,
            "risk_free_rate": float(risk_free["annual_rate"]) if risk_free else None,
            "constraints_applied": ["long_only", "max_instrument_weight"],
        },
        "warnings": ["This comparison applies long-only and maximum-instrument constraints only. Cash, sector, and eligibility constraints belong to saved Build runs and are not in this feasible set."],
    }


def capm_sml_analysis(db: Session, user: User, portfolio_id: str):
    portfolio, symbols, days, returns, _covariance, _expected, constraints, performance_benchmark_symbol, risk_free = _market_inputs(db, user, portfolio_id)
    capm_proxy_symbol, diagnostics = _capm_market_proxy_symbol(db, constraints)
    benchmark_returns = _benchmark_returns(db, capm_proxy_symbol, days)
    if not risk_free:
        diagnostics.append("No observed effective-dated risk-free series is available.")
    if benchmark_returns is None:
        diagnostics.append("At least 31 completely aligned benchmark observations are required.")
    if not capm_proxy_symbol or not risk_free or benchmark_returns is None:
        return {"available": False, "portfolio_id": portfolio.id, "data_cutoff": days[-1], "benchmark_symbol": capm_proxy_symbol, "performance_benchmark_symbol": performance_benchmark_symbol, "capm_market_proxy_symbol": capm_proxy_symbol, "risk_free": risk_free, "alignment": {"observations": 0, "sample_start": days[0], "sample_end": days[-1]}, "securities": [], "sml": [], "diagnostics": diagnostics}
    market_return = float(np.mean(benchmark_returns) * 252)
    market_risk_premium = market_return - float(risk_free["annual_rate"])
    estimate = estimate_expected_returns("capm", returns, market_returns=benchmark_returns, risk_free_rate=float(risk_free["annual_rate"]))
    realized = np.mean(returns, axis=0) * 252
    securities = [
        {
            "symbol": symbol,
            "beta": float(estimate.assumptions["betas"][index]),
            "realized_return": float(realized[index]),
            "capm_return": float(estimate.values[index]),
            "jensen_alpha": float(realized[index] - estimate.values[index]),
        }
        for index, symbol in enumerate(symbols)
    ]
    betas = [item["beta"] for item in securities]
    low_beta, high_beta = min(0.0, min(betas)), max(1.0, max(betas))
    sml = [
        {"beta": float(beta), "expected_return": float(risk_free["annual_rate"] + beta * (market_return - float(risk_free["annual_rate"])))}
        for beta in np.linspace(low_beta, high_beta, 30)
    ]
    return {
        "available": True,
        "portfolio_id": portfolio.id,
        "data_cutoff": days[-1],
        "risk_free_rate": float(risk_free["annual_rate"]),
        "market_return": market_return,
        "market_risk_premium": market_risk_premium,
        "benchmark_symbol": capm_proxy_symbol,
        "performance_benchmark_symbol": performance_benchmark_symbol,
        "capm_market_proxy_symbol": capm_proxy_symbol,
        "risk_free": risk_free,
        "alignment": {"observations": int(benchmark_returns.size), "sample_start": days[0], "sample_end": days[-1], "regression_window": int(benchmark_returns.size)},
        "securities": securities,
        "sml": sml,
        "diagnostics": ["CAPM is shown as an analytical lens and is not the sole allocation method.", *( ["Market risk premium is negative for the aligned sample."] if market_risk_premium < 0 else []), *diagnostics],
    }


def _modeled_portfolio_returns(db: Session, user: User, portfolio_id: str):
    """Return the current allocation applied to the aligned security-return matrix.

    The workstation uses this series for forward-looking comparison charts.  It is
    intentionally distinct from the ledger TWR shown on the Overview page and
    avoids replaying the transaction ledger once per historical date for each
    chart request.
    """
    portfolio, symbols, days, returns, _covariance, _expected, _constraints, _benchmark, _risk_free = _market_inputs(
        db, user, portfolio_id
    )
    summary = get_portfolio_summary(db, user, portfolio.id)
    total = float(summary.total_value)
    weights = np.asarray(
        [next((float(row.market_value) for row in summary.holdings if row.symbol == symbol), 0.0) / total if total else 0.0 for symbol in symbols],
        dtype=float,
    )
    return days, returns @ weights


def rolling_risk_analysis(db: Session, user: User, portfolio_id: str, window: int = 60):
    portfolio = get_portfolio_or_404(db, user, portfolio_id)
    price_days, values = _modeled_portfolio_returns(db, user, portfolio.id)
    days = price_days[1:]
    constraints = _selected_ips_constraints(db, portfolio)
    benchmark_symbol = _benchmark_symbol(db, portfolio, constraints)
    benchmark_returns = _benchmark_returns(db, benchmark_symbol, price_days) if days else None
    if values.size < window:
        return {"portfolio_id": portfolio.id, "window": window, "observations": int(values.size), "return_basis": "modeled_current_allocation", "benchmark_symbol": benchmark_symbol, "points": [], "diagnostics": [f"At least {window} modeled current-allocation return observations are required."]}
    wealth = np.cumprod(1 + values)
    running_peak = np.maximum.accumulate(wealth)
    points = []
    for end in range(window, len(values) + 1):
        sample = values[end - window:end]
        volatility = float(np.std(sample, ddof=1) * np.sqrt(252))
        annual_return = float(np.mean(sample) * 252)
        risk_free = _effective_risk_free_rate(db, days[end - 1], str(constraints.get("risk_free_series_key")) if constraints.get("risk_free_series_key") else None)
        annual_risk_free = float(risk_free["annual_rate"]) if risk_free else None
        benchmark_sample = benchmark_returns[end - window:end] if benchmark_returns is not None else None
        beta = None
        if benchmark_sample is not None and float(np.var(benchmark_sample, ddof=1)) > 0:
            beta = float(np.cov(sample, benchmark_sample, ddof=1)[0, 1] / np.var(benchmark_sample, ddof=1))
        points.append({
            "date": days[end - 1],
            "volatility": volatility,
            "sharpe": (annual_return - annual_risk_free) / volatility if volatility and annual_risk_free is not None else None,
            "drawdown": float(wealth[end - 1] / running_peak[end - 1] - 1),
            "beta": beta,
        })
    return {
        "portfolio_id": portfolio.id,
        "window": window,
        "observations": int(values.size),
        "return_basis": "modeled_current_allocation",
        "benchmark_symbol": benchmark_symbol,
        "risk_free": _effective_risk_free_rate(db, days[-1], str(constraints.get("risk_free_series_key")) if constraints.get("risk_free_series_key") else None),
        "points": points,
        "diagnostics": [
            "Current-allocation modeled return series; the realized ledger TWR remains on Overview.",
            *( ["Rolling beta is NOT_EVALUATED because a fully aligned performance-benchmark series is unavailable."] if benchmark_returns is None else []),
            *( ["Rolling Sharpe is NOT_EVALUATED because no effective-dated risk-free observation is available for one or more windows."] if any(point["sharpe"] is None for point in points) else []),
        ],
    }


def return_distribution_analysis(db: Session, user: User, portfolio_id: str, bins: int = 18):
    portfolio = get_portfolio_or_404(db, user, portfolio_id)
    _days, values = _modeled_portfolio_returns(db, user, portfolio.id)
    if values.size < 30:
        return {"portfolio_id": portfolio.id, "sample_size": int(values.size), "bins": [], "estimator": "bias_corrected_fisher_pearson", "diagnostics": ["At least 30 modeled current-allocation return observations are required."]}
    counts, edges = np.histogram(values, bins=bins)
    metrics = risk_metrics(values).to_dict()
    return {
        "portfolio_id": portfolio.id,
        "sample_size": int(values.size),
        "bins": [{"lower": float(edges[index]), "upper": float(edges[index + 1]), "count": int(counts[index])} for index in range(len(counts))],
        "var_95": metrics["historical_var_95"],
        "es_95": metrics["historical_es_95"],
        "var_99": metrics["historical_var_99"],
        "es_99": metrics["historical_es_99"],
        "skewness": metrics["skewness"],
        "excess_kurtosis": metrics["excess_kurtosis"],
        "estimator": "bias_corrected_fisher_pearson_skew_and_excess_kurtosis",
        "diagnostics": [
            "Historical empirical distribution of the current-allocation modeled daily return series; not the realized ledger TWR."
        ],
    }


def _weight_compliance(
    weights: dict[str, float],
    constraints: dict[str, object],
    ips_version_id: str | None,
    sectors: dict[str, str | None] | None = None,
    modeled_inputs: dict[str, object] | None = None,
):
    return evaluate_ips_constraints(
        constraints,
        [{"symbol": symbol, "weight": weight, "sector": "Cash" if symbol == "CASH" else (sectors or {}).get(symbol)} for symbol, weight in weights.items()],
        ips_version_id=ips_version_id,
        context="proposed",
        modeled_inputs=modeled_inputs,
    )


def _portfolio_metrics(asset_returns: np.ndarray, weights: np.ndarray, expected: np.ndarray, covariance: np.ndarray, risk_free_rate: float | None, required_return: float | None, cash_weight: float):
    daily = asset_returns @ weights
    metrics = risk_metrics(daily).to_dict()
    volatility = float(np.sqrt(max(weights @ covariance @ weights, 0)))
    expected_return = float(weights @ expected)
    sharpe = (expected_return - risk_free_rate) / volatility if risk_free_rate is not None and volatility else None
    return {
        "expected_return": expected_return,
        "realized_return": metrics["realized_cagr"],
        "required_return": required_return,
        "return_shortfall": expected_return - required_return if required_return is not None else None,
        "volatility": volatility,
        "sharpe": sharpe,
        "beta": None,
        "var_95": metrics["historical_var_95"],
        "es_95": metrics["historical_es_95"],
        "concentration": float(weights @ weights + cash_weight**2),
        "cash_weight": cash_weight,
    }


def compare_portfolio(db: Session, user: User, portfolio_id: str, payload: PortfolioComparisonRequest):
    portfolio, symbols, days, returns, covariance, expected, constraints, benchmark_symbol, risk_free = _market_inputs(db, user, portfolio_id)
    proposed = {key.upper(): float(value) for key, value in payload.target_weights.items()}
    weight_check = weight_diagnostics(proposed)
    if not weight_check["valid"]:
        raise HTTPException(status_code=422, detail={"code": "invalid_weight_sum", "message": "Proposed weights must be non-negative and sum to one", **weight_check})
    unknown = sorted(set(proposed) - set(symbols) - {"CASH"})
    if unknown:
        raise HTTPException(status_code=422, detail={"message": "Comparison contains securities outside the modeled portfolio universe", "symbols": unknown})
    summary = get_portfolio_summary(db, user, portfolio.id)
    total = float(summary.total_value)
    current = {row.symbol: float(row.market_value) / total if total else 0.0 for row in summary.holdings}
    current["CASH"] = float(summary.cash_balance) / total if total else 0.0
    proposed = {symbol: proposed.get(symbol, 0.0) for symbol in [*symbols, "CASH"]}
    current_risky = np.asarray([current.get(symbol, 0) for symbol in symbols])
    proposed_risky = np.asarray([proposed.get(symbol, 0) for symbol in symbols])
    annual_rf = float(risk_free["annual_rate"]) if risk_free else None
    adjusted_expected = expected.values
    cash_return = float(constraints.get("operational_cash_return", 0.0) or 0.0)
    current_expected = np.append(adjusted_expected, cash_return)
    proposed_expected = current_expected
    current_metrics = _portfolio_metrics(returns, current_risky, adjusted_expected, covariance, annual_rf, None, current["CASH"])
    proposed_metrics = _portfolio_metrics(returns, proposed_risky, adjusted_expected, covariance, annual_rf, None, proposed["CASH"])
    current_metrics["expected_return"] = float(np.append(current_risky, current["CASH"]) @ current_expected)
    proposed_metrics["expected_return"] = float(np.append(proposed_risky, proposed["CASH"]) @ proposed_expected)
    benchmark_returns = _benchmark_returns(db, benchmark_symbol, days)
    if benchmark_returns is not None and float(np.var(benchmark_returns, ddof=1)) > 0:
        betas = np.asarray([float(np.cov(returns[:, index], benchmark_returns, ddof=1)[0, 1] / np.var(benchmark_returns, ddof=1)) for index in range(len(symbols))])
        current_metrics["beta"] = float(current_risky @ betas)
        proposed_metrics["beta"] = float(proposed_risky @ betas)
    if annual_rf is not None:
        current_metrics["sharpe"] = (current_metrics["expected_return"] - annual_rf) / current_metrics["volatility"] if current_metrics["volatility"] else None
        proposed_metrics["sharpe"] = (proposed_metrics["expected_return"] - annual_rf) / proposed_metrics["volatility"] if proposed_metrics["volatility"] else None
    ips_version = db.get(PortfolioIPSVersion, portfolio.selected_ips_version_id) if portfolio.selected_ips_version_id else None
    required_return = float(ips_version.required_return) if ips_version and ips_version.required_return is not None else None
    for item in (current_metrics, proposed_metrics):
        item["required_return"] = required_return
        item["return_shortfall"] = item["expected_return"] - required_return if required_return is not None else None
    current_rc = risk_contributions(current_risky, covariance)
    proposed_rc = risk_contributions(proposed_risky, covariance)
    current_risk = dict(zip(symbols, [float(value) for value in current_rc["percentage"]], strict=True))
    proposed_risk = dict(zip(symbols, [float(value) for value in proposed_rc["percentage"]], strict=True))
    labels = {
        "expected_return": ("Expected return", "decimal", "higher"),
        "realized_return": ("Historical modeled CAGR", "decimal", "neutral"),
        "required_return": ("Required return", "decimal", "neutral"),
        "return_shortfall": ("Excess / shortfall vs required", "decimal", "higher"),
        "volatility": ("Volatility", "decimal", "lower"),
        "sharpe": ("Sharpe ratio", "ratio", "higher"),
        "beta": ("Portfolio beta", "ratio", "neutral"),
        "var_95": ("Historical VaR 95", "decimal", "lower"),
        "es_95": ("Historical ES 95", "decimal", "lower"),
        "concentration": ("Concentration HHI", "ratio", "lower"),
        "cash_weight": ("Cash weight", "decimal", "neutral"),
    }
    metrics = []
    trade_offs = []
    for key, (label, unit, direction) in labels.items():
        before, after = current_metrics.get(key), proposed_metrics.get(key)
        delta = after - before if before is not None and after is not None else None
        classification = "NOT_EVALUATED" if delta is None else "REFERENCE" if direction == "neutral" else "UNCHANGED" if abs(delta) <= CHANGE_TOLERANCE else "IMPROVED" if (delta > 0 if direction == "higher" else delta < 0) else "WORSENED"
        metrics.append({"key": key, "label": label, "unit": unit, "current": before, "proposed": after, "delta": delta, "preferred_direction": direction, "classification": classification, "availability_note": "A confirmed IPS goal is required." if key in {"required_return", "return_shortfall"} and required_return is None else None})
        if direction != "neutral":
            trade_offs.append({"metric": key, "label": label, "direction": classification, "delta": delta, "unit": unit})
    return {
        "portfolio_id": portfolio.id,
        "label": payload.label,
        "data_cutoff": days[-1],
        "assumptions": {"expected_return_method": expected.method, "expected_return": expected.assumptions, "covariance": "diagonal_shrinkage", "risk_free": risk_free, "cash": {"instrument": "operational_cash", "annual_return": cash_return, "basis": "nominal", "effective_date": days[-1].isoformat()}, "cash_covariance": 0.0},
        "current_weights": current,
        "proposed_weights": proposed,
        "metrics": metrics,
        "current_risk_contributions": current_risk,
        "proposed_risk_contributions": proposed_risk,
        "current_compliance": ips_compliance(db, user, portfolio.id),
        "proposed_compliance": _weight_compliance(
            proposed,
            constraints,
            portfolio.selected_ips_version_id,
            {row.symbol: row.sector for row in summary.holdings},
            {
                "portfolio_volatility": proposed_metrics.get("volatility"),
                "portfolio_beta": proposed_metrics.get("beta"),
                "risk_contributions": proposed_risk,
                "liquid_assets": proposed.get("CASH", 0.0) * total,
                "data_cutoff": days[-1],
                "estimator": "historical_shrunk_aligned_price_covariance_v1",
            },
        ),
        "trade_offs": trade_offs,
        "warnings": [] if required_return is not None else ["Required-return comparison is unavailable until the confirmed IPS contains a calculable goal."],
    }


def risk_budget_analysis(db: Session, user: User, portfolio_id: str, target: dict[str, float] | None = None):
    portfolio, symbols, days, _returns, covariance, _expected, constraints, _benchmark, _risk_free = _market_inputs(db, user, portfolio_id)
    summary = get_portfolio_summary(db, user, portfolio.id)
    values = {row.symbol: float(row.market_value) for row in summary.holdings}
    risky_total = sum(values.values())
    total_capital = float(summary.total_value)
    risky_weights = np.asarray([values.get(symbol, 0) / risky_total for symbol in symbols])
    total_weights = np.asarray([values.get(symbol, 0) / total_capital if total_capital else 0.0 for symbol in symbols])
    contribution = risk_contributions(risky_weights, covariance)
    configured = target or constraints.get("risk_budgets")
    normalized = None
    if configured:
        try:
            raw = np.asarray([float(configured[symbol]) for symbol in symbols])
        except KeyError as exc:
            raise HTTPException(status_code=422, detail=f"Missing target risk budget for {exc.args[0]}") from exc
        if np.any(raw < 0) or raw.sum() <= 0:
            raise HTTPException(status_code=422, detail="Risk budgets must be non-negative and have a positive sum")
        normalized = raw / raw.sum()
    items = []
    for index, symbol in enumerate(symbols):
        actual = float(contribution["percentage"][index])
        target_value = float(normalized[index]) if normalized is not None else None
        items.append({"symbol": symbol, "total_capital_weight": float(total_weights[index]), "risky_sleeve_weight": float(risky_weights[index]), "component_risk": float(contribution["component"][index]), "percentage_risk": actual, "target_risk": target_value, "residual": actual - target_value if target_value is not None else None})
    cash_weight = float(summary.cash_balance) / total_capital if total_capital else 0.0
    items.append({"symbol": "CASH", "total_capital_weight": cash_weight, "risky_sleeve_weight": None, "component_risk": 0.0, "percentage_risk": 0.0, "target_risk": None, "residual": None})
    error = float(np.sqrt(np.sum((np.asarray(contribution["percentage"]) - normalized) ** 2))) if normalized is not None else None
    return {"portfolio_id": portfolio.id, "data_cutoff": days[-1], "portfolio_basis": "total_capital", "items": items, "total_percentage_risk": float(np.sum(contribution["percentage"])), "residual_error": error, "diagnostics": [] if normalized is not None else ["No target risk budget is configured; actual contribution is shown without a target."]}
