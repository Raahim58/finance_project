from dataclasses import asdict, dataclass

import numpy as np


@dataclass(frozen=True)
class OptimizationResult:
    status: str
    weights: list[float]
    expected_return: float | None
    volatility: float | None
    diagnostics: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _project_bounded_simplex(values: np.ndarray, lower: np.ndarray, upper: np.ndarray) -> np.ndarray:
    if lower.sum() > 1 + 1e-10 or upper.sum() < 1 - 1e-10:
        raise ValueError("Weight bounds are infeasible")
    lo, hi = float(np.min(values - upper)), float(np.max(values - lower))
    for _ in range(100):
        midpoint = (lo + hi) / 2
        projected = np.clip(values - midpoint, lower, upper)
        if projected.sum() > 1:
            lo = midpoint
        else:
            hi = midpoint
    return np.clip(values - (lo + hi) / 2, lower, upper)


def optimize(
    covariance: np.ndarray,
    *,
    objective: str = "minimum_variance",
    expected_returns: np.ndarray | None = None,
    target_return: float | None = None,
    lower_bounds: list[float] | None = None,
    upper_bounds: list[float] | None = None,
) -> OptimizationResult:
    covariance = np.asarray(covariance, dtype=float)
    if covariance.ndim != 2 or covariance.shape[0] != covariance.shape[1]:
        raise ValueError("covariance must be square")
    count = covariance.shape[0]
    lower = np.asarray(lower_bounds or [0.0] * count, dtype=float)
    upper = np.asarray(upper_bounds or [1.0] * count, dtype=float)
    if lower.shape != (count,) or upper.shape != (count,) or np.any(lower > upper):
        raise ValueError("Invalid weight bounds")
    if np.min(np.linalg.eigvalsh((covariance + covariance.T) / 2)) < -1e-8:
        raise ValueError("covariance must be positive semidefinite")
    if objective not in {"minimum_variance", "target_return_minimum_variance"}:
        raise ValueError("Unsupported objective")
    if objective == "target_return_minimum_variance" and (expected_returns is None or target_return is None):
        raise ValueError("Target-return optimization requires expected returns and a target")
    weights = _project_bounded_simplex(np.full(count, 1 / count), lower, upper)
    step = 0.2 / max(float(np.linalg.norm(covariance, 2)), 1e-9)
    for iteration in range(5000):
        candidate = _project_bounded_simplex(weights - step * (2 * covariance @ weights), lower, upper)
        if objective == "target_return_minimum_variance" and float(candidate @ expected_returns) < target_return:
            direction = expected_returns - float(np.mean(expected_returns))
            candidate = _project_bounded_simplex(candidate + step * direction, lower, upper)
        if np.linalg.norm(candidate - weights) < 1e-10:
            weights = candidate
            break
        weights = candidate
    achieved_return = float(weights @ expected_returns) if expected_returns is not None else None
    if target_return is not None and (achieved_return is None or achieved_return + 1e-6 < target_return):
        return OptimizationResult("infeasible", [], None, None, {"reason": "target_return_conflicts_with_bounds"})
    volatility = float(np.sqrt(max(weights @ covariance @ weights, 0)))
    return OptimizationResult(
        "optimal",
        weights.tolist(),
        achieved_return,
        volatility,
        {"iterations": iteration + 1, "solver": "deterministic_projected_gradient", "constraints_relaxed": False},
    )
