"""Shared numerical and presentation contracts for decision analytics."""

WEIGHT_TOLERANCE = 1e-6
WEIGHT_DECIMAL_PLACES = 6
DEFAULT_MAX_CASH_WEIGHT = 0.20
DEFAULT_OPERATIONAL_CASH_RETURN = 0.0
CHANGE_TOLERANCE = 1e-8


def weight_diagnostics(weights: dict[str, float]) -> dict[str, float | bool]:
    submitted_sum = round(sum(float(value) for value in weights.values()), 12)
    residual = round(1.0 - submitted_sum, 12)
    return {
        "submitted_sum": submitted_sum,
        "residual": residual,
        "tolerance": WEIGHT_TOLERANCE,
        "valid": all(float(value) >= 0 for value in weights.values()) and abs(residual) <= WEIGHT_TOLERANCE,
    }

