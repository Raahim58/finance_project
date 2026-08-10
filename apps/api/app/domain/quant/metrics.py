from dataclasses import asdict, dataclass

import numpy as np


@dataclass(frozen=True)
class RiskMetrics:
    annual_return: float
    annual_volatility: float
    downside_deviation: float
    max_drawdown: float
    historical_var_95: float
    historical_es_95: float
    historical_var_99: float
    historical_es_99: float
    skewness: float
    excess_kurtosis: float
    sample_size: int
    annualization: int = 252

    def to_dict(self) -> dict[str, float | int]:
        return asdict(self)


def _finite(values: np.ndarray, minimum: int = 2) -> np.ndarray:
    result = np.asarray(values, dtype=float)
    if result.size < minimum or not np.all(np.isfinite(result)):
        raise ValueError(f"At least {minimum} finite observations are required")
    return result


def return_matrix(price_columns: list[list[float]]) -> np.ndarray:
    prices = np.asarray(price_columns, dtype=float).T
    if prices.ndim != 2 or prices.shape[0] < 2 or np.any(prices <= 0) or not np.all(np.isfinite(prices)):
        raise ValueError("At least two aligned, finite, positive prices are required")
    return prices[1:] / prices[:-1] - 1.0


def log_return_matrix(price_columns: list[list[float]]) -> np.ndarray:
    return np.log1p(return_matrix(price_columns))


def cumulative_returns(returns: np.ndarray) -> np.ndarray:
    values = _finite(np.asarray(returns))
    return np.cumprod(1 + values, axis=0) - 1


def drawdown_series(returns: np.ndarray) -> np.ndarray:
    values = _finite(np.asarray(returns))
    wealth = np.cumprod(1 + values, axis=0)
    return wealth / np.maximum.accumulate(wealth, axis=0) - 1


def covariance_matrix(returns: np.ndarray, shrinkage: float = 0.20, annualization: int = 252) -> np.ndarray:
    if not 0 <= shrinkage <= 1:
        raise ValueError("shrinkage must be between 0 and 1")
    if returns.ndim != 2 or returns.shape[0] < 2:
        raise ValueError("At least two aligned return observations are required")
    sample = np.atleast_2d(np.cov(returns, rowvar=False, ddof=1))
    diagonal = np.diag(np.diag(sample))
    result = ((1 - shrinkage) * sample + shrinkage * diagonal) * annualization
    return (result + result.T) / 2


def correlation_matrix(returns: np.ndarray) -> np.ndarray:
    if returns.ndim != 2 or returns.shape[0] < 2:
        raise ValueError("At least two aligned return observations are required")
    return np.atleast_2d(np.corrcoef(returns, rowvar=False))


def regression_metrics(asset_returns: np.ndarray, benchmark_returns: np.ndarray, annualization: int = 252) -> dict[str, float | int]:
    asset = _finite(asset_returns, 60)
    benchmark = _finite(benchmark_returns, 60)
    if asset.shape != benchmark.shape:
        raise ValueError("Asset and benchmark returns must be aligned")
    design = np.column_stack([np.ones(asset.size), benchmark])
    alpha_daily, beta = np.linalg.lstsq(design, asset, rcond=None)[0]
    residuals = asset - design @ np.array([alpha_daily, beta])
    return {"alpha": float(alpha_daily * annualization), "beta": float(beta), "residual_volatility": float(np.std(residuals, ddof=2) * np.sqrt(annualization)), "sample_size": int(asset.size)}


def capm_required_return(beta: float, risk_free_rate: float, market_expected_return: float) -> float:
    return float(risk_free_rate + beta * (market_expected_return - risk_free_rate))


def tail_risk(returns: np.ndarray, confidence: float) -> tuple[float, float]:
    if not 0 < confidence < 1:
        raise ValueError("confidence must be between zero and one")
    values = _finite(returns)
    cutoff = float(np.quantile(values, 1 - confidence))
    tail = values[values <= cutoff]
    return float(-cutoff), float(-np.mean(tail))


def risk_metrics(returns: list[float] | np.ndarray, annualization: int = 252) -> RiskMetrics:
    values = _finite(np.asarray(returns, dtype=float))
    var95, es95 = tail_risk(values, 0.95)
    var99, es99 = tail_risk(values, 0.99)
    centered = values - np.mean(values)
    standard = float(np.std(values, ddof=1))
    skewness = float(np.mean(centered**3) / standard**3) if standard else 0.0
    excess_kurtosis = float(np.mean(centered**4) / standard**4 - 3) if standard else 0.0
    downside = values[values < 0]
    return RiskMetrics(
        annual_return=float(np.mean(values) * annualization),
        annual_volatility=float(standard * np.sqrt(annualization)),
        downside_deviation=float(np.sqrt(np.mean(downside**2)) * np.sqrt(annualization)) if downside.size else 0.0,
        max_drawdown=float(np.min(drawdown_series(values))),
        historical_var_95=var95,
        historical_es_95=es95,
        historical_var_99=var99,
        historical_es_99=es99,
        skewness=skewness,
        excess_kurtosis=excess_kurtosis,
        sample_size=int(values.size),
        annualization=annualization,
    )


def performance_ratios(returns: np.ndarray, *, risk_free_rate: float = 0.0, benchmark_returns: np.ndarray | None = None, annualization: int = 252) -> dict[str, float | None]:
    values = _finite(returns)
    annual_return = float(np.mean(values) * annualization)
    volatility = float(np.std(values, ddof=1) * np.sqrt(annualization))
    result: dict[str, float | None] = {"sharpe": (annual_return - risk_free_rate) / volatility if volatility else None}
    if benchmark_returns is None:
        result.update({"tracking_error": None, "information_ratio": None, "treynor": None, "jensen_alpha": None, "m2": None})
        return result
    benchmark = _finite(benchmark_returns)
    if benchmark.shape != values.shape:
        raise ValueError("Benchmark returns must be aligned")
    active = values - benchmark
    tracking_error = float(np.std(active, ddof=1) * np.sqrt(annualization))
    regression = regression_metrics(values, benchmark)
    beta = float(regression["beta"])
    benchmark_vol = float(np.std(benchmark, ddof=1) * np.sqrt(annualization))
    result.update({
        "tracking_error": tracking_error,
        "information_ratio": float(np.mean(active) * annualization / tracking_error) if tracking_error else None,
        "treynor": (annual_return - risk_free_rate) / beta if beta else None,
        "jensen_alpha": float(regression["alpha"]),
        "m2": risk_free_rate + ((annual_return - risk_free_rate) / volatility * benchmark_vol) if volatility else None,
    })
    return result


def risk_contributions(weights: np.ndarray, covariance: np.ndarray) -> dict[str, np.ndarray | float]:
    weights = np.asarray(weights, dtype=float)
    covariance = np.asarray(covariance, dtype=float)
    variance = float(weights @ covariance @ weights)
    volatility = float(np.sqrt(max(variance, 0)))
    marginal = covariance @ weights / volatility if volatility else np.zeros_like(weights)
    component = weights * marginal
    percentage = component / volatility if volatility else np.zeros_like(weights)
    return {"variance": variance, "volatility": volatility, "marginal": marginal, "component": component, "percentage": percentage}
