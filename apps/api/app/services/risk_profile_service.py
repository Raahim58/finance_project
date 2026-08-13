RISK_ORDER = {"low": 0, "moderate": 1, "high": 2}


def _risk_level_from_score(score: float) -> str:
    if score < 2.5:
        return "low"
    if score < 3.75:
        return "moderate"
    return "high"


def assess_risk_profile(data: dict[str, object]) -> dict[str, object]:
    """Reconcile capacity and willingness without claiming psychometric precision."""
    diagnostics: list[str] = []
    capacity = None
    has_financial_inputs = any(data.get(key) is not None for key in ("horizon_years", "expense_coverage_months", "portfolio_income_dependence", "drawdown_capacity"))
    if has_financial_inputs:
        horizon = data.get("horizon_years"); coverage = data.get("expense_coverage_months")
        income_dependence = str(data.get("portfolio_income_dependence") or "").lower(); drawdown_ability = str(data.get("drawdown_capacity") or "").lower()
        scores: list[float] = []
        if isinstance(horizon, (int, float)): scores.append(1 if horizon < 3 else 3 if horizon < 8 else 5)
        if isinstance(coverage, (int, float)): scores.append(1 if coverage < 3 else 3 if coverage < 12 else 5)
        if income_dependence in RISK_ORDER: scores.append({"high": 1, "moderate": 3, "low": 5}[income_dependence])
        if drawdown_ability in RISK_ORDER: scores.append({"low": 1, "moderate": 3, "high": 5}[drawdown_ability])
        if scores:
            capacity = _risk_level_from_score(sum(scores) / len(scores)); diagnostics.append("Capacity is a rule-based estimate from the financial inputs provided.")
        else: diagnostics.append("Risk capacity is unavailable because financial resilience inputs are incomplete.")
    else: diagnostics.append("Risk capacity is unavailable because financial resilience inputs are incomplete.")
    willingness = str(data.get("risk_willingness") or "").lower() or None
    answers = data.get("willingness_answers"); numeric_answers = [float(value) for value in answers if isinstance(value, (int, float))] if isinstance(answers, list) else []
    if numeric_answers:
        willingness = _risk_level_from_score(sum(numeric_answers) / len(numeric_answers)); diagnostics.append("Willingness is a directional questionnaire result, not a scientific measurement.")
    elif willingness not in RISK_ORDER:
        willingness = None; diagnostics.append("Risk willingness is unavailable because behavioural responses are incomplete.")
    reconciled = min((capacity, willingness), key=lambda value: RISK_ORDER[value]) if capacity and willingness else None
    if reconciled: diagnostics.append("Reconciled tolerance is bounded by the more restrictive of capacity and willingness.")
    confirmed = str(data.get("confirmed_overall_risk_tolerance") or data.get("overall_risk_tolerance") or "").lower() or None
    if confirmed not in RISK_ORDER: confirmed = None
    if confirmed and reconciled and RISK_ORDER[confirmed] > RISK_ORDER[reconciled]: diagnostics.append("The confirmed tolerance exceeds the conservative reconciled assessment; review before using it in a mandate.")
    return {"capacity": capacity, "willingness": willingness, "reconciled_tolerance": reconciled, "confirmed_tolerance": confirmed, "available": bool(capacity and willingness), "diagnostics": diagnostics}
