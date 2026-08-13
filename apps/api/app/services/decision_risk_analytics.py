import numpy as np
from sqlalchemy.orm import Session

from app.domain.quant import risk_metrics
from app.models.user import User
from app.services.decision_market_inputs import benchmark_returns, market_inputs
from app.services.portfolio_service import get_portfolio_or_404, get_portfolio_summary
from app.services.workstation_service import _benchmark_symbol, _effective_risk_free_rate, _selected_ips_constraints


def _modeled_portfolio_returns(db: Session, user: User, portfolio_id: str):
    portfolio, symbols, days, returns, *_ = market_inputs(db, user, portfolio_id)
    summary = get_portfolio_summary(db, user, portfolio.id); total = float(summary.total_value)
    weights = np.asarray([next((float(row.market_value) for row in summary.holdings if row.symbol == symbol), 0.0) / total if total else 0.0 for symbol in symbols], dtype=float)
    return days, returns @ weights


def rolling_risk_analysis(db: Session, user: User, portfolio_id: str, window: int = 60, risk_free_loader=None):
    portfolio = get_portfolio_or_404(db, user, portfolio_id); price_days, values = _modeled_portfolio_returns(db, user, portfolio.id); days = price_days[1:]
    constraints = _selected_ips_constraints(db, portfolio); benchmark_symbol = _benchmark_symbol(db, portfolio, constraints)
    aligned_benchmark = benchmark_returns(db, benchmark_symbol, price_days) if days else None
    loader = risk_free_loader or _effective_risk_free_rate
    if values.size < window:
        return {"portfolio_id": portfolio.id, "window": window, "observations": int(values.size), "return_basis": "modeled_current_allocation", "benchmark_symbol": benchmark_symbol, "points": [], "diagnostics": [f"At least {window} modeled current-allocation return observations are required."]}
    wealth = np.cumprod(1 + values); running_peak = np.maximum.accumulate(wealth); points = []
    for end in range(window, len(values) + 1):
        sample = values[end - window:end]; volatility = float(np.std(sample, ddof=1) * np.sqrt(252)); annual_return = float(np.mean(sample) * 252)
        risk_free = loader(db, days[end - 1], str(constraints.get("risk_free_series_key")) if constraints.get("risk_free_series_key") else None); annual_risk_free = float(risk_free["annual_rate"]) if risk_free else None
        benchmark_sample = aligned_benchmark[end - window:end] if aligned_benchmark is not None else None; beta = None
        if benchmark_sample is not None and float(np.var(benchmark_sample, ddof=1)) > 0: beta = float(np.cov(sample, benchmark_sample, ddof=1)[0, 1] / np.var(benchmark_sample, ddof=1))
        points.append({"date": days[end - 1], "volatility": volatility, "sharpe": (annual_return - annual_risk_free) / volatility if volatility and annual_risk_free is not None else None, "drawdown": float(wealth[end - 1] / running_peak[end - 1] - 1), "beta": beta})
    return {"portfolio_id": portfolio.id, "window": window, "observations": int(values.size), "return_basis": "modeled_current_allocation", "benchmark_symbol": benchmark_symbol, "risk_free": loader(db, days[-1], str(constraints.get("risk_free_series_key")) if constraints.get("risk_free_series_key") else None), "points": points, "diagnostics": ["Current-allocation modeled return series; the realized ledger TWR remains on Overview.", *(["Rolling beta is NOT_EVALUATED because a fully aligned performance-benchmark series is unavailable."] if aligned_benchmark is None else []), *(["Rolling Sharpe is NOT_EVALUATED because no effective-dated risk-free observation is available for one or more windows."] if any(point["sharpe"] is None for point in points) else [])]}


def return_distribution_analysis(db: Session, user: User, portfolio_id: str, bins: int = 18):
    portfolio = get_portfolio_or_404(db, user, portfolio_id); _days, values = _modeled_portfolio_returns(db, user, portfolio.id)
    if values.size < 30: return {"portfolio_id": portfolio.id, "sample_size": int(values.size), "bins": [], "estimator": "bias_corrected_fisher_pearson", "diagnostics": ["At least 30 modeled current-allocation return observations are required."]}
    counts, edges = np.histogram(values, bins=bins); metrics = risk_metrics(values).to_dict()
    return {"portfolio_id": portfolio.id, "sample_size": int(values.size), "bins": [{"lower": float(edges[index]), "upper": float(edges[index + 1]), "count": int(counts[index])} for index in range(len(counts))], "var_95": metrics["historical_var_95"], "es_95": metrics["historical_es_95"], "var_99": metrics["historical_var_99"], "es_99": metrics["historical_es_99"], "skewness": metrics["skewness"], "excess_kurtosis": metrics["excess_kurtosis"], "estimator": "bias_corrected_fisher_pearson_skew_and_excess_kurtosis", "diagnostics": ["Historical empirical distribution of the current-allocation modeled daily return series; not the realized ledger TWR."]}
