from dataclasses import asdict, dataclass

import cvxpy as cp
import numpy as np
from scipy.optimize import minimize


@dataclass(frozen=True)
class OptimizationResult:
    status: str
    weights: list[float]
    expected_return: float | None
    volatility: float | None
    diagnostics: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _validate(covariance: np.ndarray, lower: np.ndarray, upper: np.ndarray) -> None:
    if covariance.ndim != 2 or covariance.shape[0] != covariance.shape[1]:
        raise ValueError("covariance must be square")
    if lower.shape != (covariance.shape[0],) or upper.shape != (covariance.shape[0],) or np.any(lower > upper):
        raise ValueError("Invalid weight bounds")
    if lower.sum() > 1 + 1e-10 or upper.sum() < 1 - 1e-10:
        raise ValueError("Weight bounds are infeasible")
    if np.min(np.linalg.eigvalsh((covariance + covariance.T) / 2)) < -1e-8:
        raise ValueError("covariance must be positive semidefinite")


def _solve(problem: cp.Problem) -> tuple[str, list[dict[str, object]]]:
    attempts = []
    for solver in (cp.CLARABEL, cp.OSQP, cp.SCS):
        try:
            problem.solve(solver=solver, verbose=False)
            attempts.append({"solver": solver, "status": problem.status})
            if problem.status in {cp.OPTIMAL, cp.OPTIMAL_INACCURATE}:
                return str(solver), attempts
        except Exception as exc:
            attempts.append({"solver": str(solver), "status": "error", "error": type(exc).__name__})
    return "none", attempts


def _convex_optimize(
    covariance: np.ndarray,
    objective: str,
    expected_returns: np.ndarray | None,
    target_return: float | None,
    target_volatility: float | None,
    target_beta: float | None,
    betas: np.ndarray | None,
    lower: np.ndarray,
    upper: np.ndarray,
    linear_upper_bounds: list[tuple[np.ndarray, float, str]] | None = None,
) -> OptimizationResult:
    count = covariance.shape[0]
    weights = cp.Variable(count)
    variance = cp.quad_form(weights, cp.psd_wrap(covariance))
    constraints = [cp.sum(weights) == 1, weights >= lower, weights <= upper]
    for coefficients, limit, _label in linear_upper_bounds or []:
        constraints.append(np.asarray(coefficients, dtype=float) @ weights <= float(limit))
    if target_return is not None:
        if expected_returns is None:
            raise ValueError("Target return requires expected returns")
        constraints.append(expected_returns @ weights >= target_return)
    if target_volatility is not None:
        constraints.append(variance <= target_volatility**2)
    if target_beta is not None:
        if betas is None:
            raise ValueError("Target beta requires asset beta estimates")
        constraints.append(betas @ weights == target_beta)
    expression = cp.Minimize(variance)
    if objective == "target_volatility_maximum_return":
        if expected_returns is None or target_volatility is None:
            raise ValueError("Target-volatility optimization requires expected returns and target volatility")
        expression = cp.Maximize(expected_returns @ weights)
    problem = cp.Problem(expression, constraints)
    solver, attempts = _solve(problem)
    if problem.status not in {cp.OPTIMAL, cp.OPTIMAL_INACCURATE} or weights.value is None:
        return OptimizationResult("infeasible" if problem.status in {cp.INFEASIBLE, cp.INFEASIBLE_INACCURATE} else "failed", [], None, None, {"solver_attempts": attempts, "reason": str(problem.status), "constraints_relaxed": False, "active_group_constraints": [label for _, _, label in linear_upper_bounds or []], "nearest_relaxations": ["Increase one or more upper bounds", "Reduce minimum cash/weight requirements", "Relax target return, volatility, beta, or sector caps"]})
    values = np.asarray(weights.value, dtype=float)
    values[np.abs(values) < 1e-10] = 0
    values /= values.sum()
    achieved_return = float(values @ expected_returns) if expected_returns is not None else None
    volatility = float(np.sqrt(max(values @ covariance @ values, 0)))
    return OptimizationResult("optimal", values.tolist(), achieved_return, volatility, {"solver": solver, "solver_attempts": attempts, "constraints_relaxed": False})


def _risk_budget_optimize(covariance: np.ndarray, lower: np.ndarray, upper: np.ndarray, budgets: np.ndarray | None) -> OptimizationResult:
    count = covariance.shape[0]
    target = np.asarray(budgets if budgets is not None else np.full(count, 1 / count), dtype=float)
    if target.shape != (count,) or np.any(target < 0) or target.sum() <= 0:
        raise ValueError("Risk budgets must be non-negative and match asset count")
    target /= target.sum()

    def objective(weights: np.ndarray) -> float:
        variance = float(weights @ covariance @ weights)
        if variance <= 0:
            return 1e9
        contribution = weights * (covariance @ weights) / variance
        return float(np.sum((contribution - target) ** 2))

    starts = [np.full(count, 1 / count)]
    starts.extend(np.eye(count)[index] * 0.8 + np.full(count, 0.2 / count) for index in range(count))
    best = None
    diagnostics = []
    for start in starts:
        result = minimize(objective, np.clip(start, lower, upper), method="SLSQP", bounds=list(zip(lower, upper, strict=True)), constraints={"type": "eq", "fun": lambda w: np.sum(w) - 1}, options={"maxiter": 2000, "ftol": 1e-12})
        diagnostics.append({"success": bool(result.success), "message": str(result.message), "iterations": int(result.nit)})
        if result.success and (best is None or result.fun < best.fun):
            best = result
    if best is None:
        return OptimizationResult("failed", [], None, None, {"solver": "SLSQP", "attempts": diagnostics, "constraints_relaxed": False})
    weights = np.asarray(best.x, dtype=float)
    return OptimizationResult("optimal", weights.tolist(), None, float(np.sqrt(max(weights @ covariance @ weights, 0))), {"solver": "SLSQP", "attempts": diagnostics, "risk_budgets": target.tolist(), "constraints_relaxed": False})


def optimize(
    covariance: np.ndarray,
    *,
    objective: str = "minimum_variance",
    expected_returns: np.ndarray | None = None,
    target_return: float | None = None,
    target_volatility: float | None = None,
    target_beta: float | None = None,
    betas: np.ndarray | None = None,
    risk_budgets: np.ndarray | None = None,
    risk_free_rate: float = 0.0,
    lower_bounds: list[float] | None = None,
    upper_bounds: list[float] | None = None,
    linear_upper_bounds: list[tuple[np.ndarray, float, str]] | None = None,
) -> OptimizationResult:
    covariance = np.asarray(covariance, dtype=float)
    count = covariance.shape[0] if covariance.ndim == 2 else 0
    lower = np.asarray(lower_bounds or [0.0] * count, dtype=float)
    upper = np.asarray(upper_bounds or [1.0] * count, dtype=float)
    _validate(covariance, lower, upper)
    supported = {"minimum_variance", "target_return_minimum_variance", "target_volatility_maximum_return", "target_beta", "max_sharpe", "risk_parity", "risk_budget"}
    if objective not in supported:
        raise ValueError("Unsupported objective")
    if expected_returns is not None:
        expected_returns = np.asarray(expected_returns, dtype=float)
        if expected_returns.shape != (count,) or not np.all(np.isfinite(expected_returns)):
            raise ValueError("Expected returns must match asset count and be finite")
    if objective in {"risk_parity", "risk_budget"}:
        if linear_upper_bounds:
            raise ValueError("Risk-budget objectives do not support group constraints")
        return _risk_budget_optimize(covariance, lower, upper, risk_budgets if objective == "risk_budget" else None)
    if objective == "target_return_minimum_variance" and target_return is None:
        raise ValueError("Target-return optimization requires a target")
    if objective == "target_beta" and target_beta is None:
        raise ValueError("Target-beta optimization requires a target")
    if objective == "max_sharpe":
        if expected_returns is None:
            raise ValueError("Max Sharpe requires expected returns")
        candidates = []
        for target in np.linspace(float(np.min(expected_returns)), float(np.max(expected_returns)), 40):
            candidate = _convex_optimize(covariance, "target_return_minimum_variance", expected_returns, float(target), None, None, None, lower, upper, linear_upper_bounds)
            if candidate.status == "optimal" and candidate.volatility and candidate.expected_return is not None:
                candidates.append(((candidate.expected_return - risk_free_rate) / candidate.volatility, candidate))
        if not candidates:
            return OptimizationResult("infeasible", [], None, None, {"reason": "no_feasible_frontier_portfolio", "constraints_relaxed": False})
        _, best = max(candidates, key=lambda item: item[0])
        return OptimizationResult(best.status, best.weights, best.expected_return, best.volatility, {**best.diagnostics, "method": "deterministic_target_return_grid", "grid_size": 40})
    return _convex_optimize(covariance, objective, expected_returns, target_return, target_volatility, target_beta, betas, lower, upper, linear_upper_bounds)
