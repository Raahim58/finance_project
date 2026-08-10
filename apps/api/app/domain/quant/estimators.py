from dataclasses import dataclass

import numpy as np


METHODS = {"capm", "historical_shrunk", "user_model"}


@dataclass(frozen=True)
class ExpectedReturnEstimate:
    method: str
    values: np.ndarray
    assumptions: dict[str, object]


def estimate_expected_returns(
    method: str,
    returns: np.ndarray,
    *,
    market_returns: np.ndarray | None = None,
    risk_free_rate: float | None = None,
    assumptions: list[float] | None = None,
    shrinkage: float = 0.50,
    annualization: int = 252,
) -> ExpectedReturnEstimate:
    if method not in METHODS:
        raise ValueError(f"Unknown expected-return method: {method}")
    if returns.ndim != 2:
        raise ValueError("returns must be a two-dimensional matrix")
    if method == "user_model":
        if assumptions is None or len(assumptions) != returns.shape[1]:
            raise ValueError("user_model requires one explicit assumption per asset")
        values = np.asarray(assumptions, dtype=float)
        return ExpectedReturnEstimate(method, values, {"source": "user_or_model"})
    if method == "historical_shrunk":
        means = np.mean(returns, axis=0) * annualization
        grand_mean = float(np.mean(means))
        values = (1 - shrinkage) * means + shrinkage * grand_mean
        return ExpectedReturnEstimate(method, values, {"shrinkage": shrinkage, "annualization": annualization})
    if market_returns is None or risk_free_rate is None or market_returns.shape[0] != returns.shape[0]:
        raise ValueError("capm requires aligned market returns and an effective-dated risk-free rate")
    market_variance = float(np.var(market_returns, ddof=1))
    if market_variance <= 0:
        raise ValueError("capm market variance must be positive")
    betas = np.array([np.cov(returns[:, i], market_returns, ddof=1)[0, 1] / market_variance for i in range(returns.shape[1])])
    market_premium = float(np.mean(market_returns) * annualization - risk_free_rate)
    return ExpectedReturnEstimate(
        method,
        risk_free_rate + betas * market_premium,
        {"risk_free_rate": risk_free_rate, "market_premium": market_premium, "betas": betas.tolist()},
    )
