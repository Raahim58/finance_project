from dataclasses import asdict, dataclass

import numpy as np


@dataclass(frozen=True)
class RiskMetrics:
    annual_return: float
    annual_volatility: float
    max_drawdown: float
    historical_var_95: float
    historical_es_95: float
    sample_size: int
    annualization: int = 252

    def to_dict(self) -> dict[str, float | int]:
        return asdict(self)


def return_matrix(price_columns: list[list[float]]) -> np.ndarray:
    prices = np.asarray(price_columns, dtype=float).T
    if prices.ndim != 2 or prices.shape[0] < 2 or np.any(prices <= 0) or not np.all(np.isfinite(prices)):
        raise ValueError("At least two aligned, finite, positive prices are required")
    return prices[1:] / prices[:-1] - 1.0


def covariance_matrix(returns: np.ndarray, shrinkage: float = 0.20, annualization: int = 252) -> np.ndarray:
    if not 0 <= shrinkage <= 1:
        raise ValueError("shrinkage must be between 0 and 1")
    if returns.ndim != 2 or returns.shape[0] < 2:
        raise ValueError("At least two aligned return observations are required")
    sample = np.atleast_2d(np.cov(returns, rowvar=False, ddof=1))
    diagonal = np.diag(np.diag(sample))
    result = ((1 - shrinkage) * sample + shrinkage * diagonal) * annualization
    return (result + result.T) / 2


def risk_metrics(returns: list[float], annualization: int = 252) -> RiskMetrics:
    values = np.asarray(returns, dtype=float)
    if values.size < 2 or not np.all(np.isfinite(values)):
        raise ValueError("At least two finite returns are required")
    wealth = np.cumprod(1 + values)
    drawdowns = wealth / np.maximum.accumulate(wealth) - 1
    cutoff = float(np.quantile(values, 0.05))
    tail = values[values <= cutoff]
    return RiskMetrics(
        annual_return=float(np.mean(values) * annualization),
        annual_volatility=float(np.std(values, ddof=1) * np.sqrt(annualization)),
        max_drawdown=float(np.min(drawdowns)),
        historical_var_95=float(-cutoff),
        historical_es_95=float(-np.mean(tail)),
        sample_size=int(values.size),
        annualization=annualization,
    )
