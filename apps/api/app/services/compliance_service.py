from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable, Literal, TypedDict


ComplianceStatus = Literal["PASS", "BREACH", "NOT_EVALUATED"]


class PositionInput(TypedDict, total=False):
    symbol: str
    weight: float
    sector: str | None
    shariah_eligible: bool | None
    asset_type: str | None
    currency: str | None


def _check(
    code: str,
    label: str,
    status: ComplianceStatus,
    *,
    message: str,
    actual: Any = None,
    limit: Any = None,
    severity: str = "hard",
    **context: Any,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "code": code,
        "label": label,
        "status": status,
        "message": message,
        "severity": severity,
    }
    if actual is not None:
        result["actual"] = actual
    if limit is not None:
        result["limit"] = limit
    result.update({key: value for key, value in context.items() if value is not None})
    return result


def evaluate_ips_constraints(
    constraints: dict[str, Any],
    positions: Iterable[PositionInput],
    *,
    ips_version_id: str | None,
    valuation_complete: bool = True,
    unpriced_symbols: list[str] | None = None,
    context: str = "current",
    modeled_inputs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate every portfolio state through one deterministic IPS contract.

    A portfolio is compliant when no evaluated hard check breaches. Missing inputs
    remain visible as NOT_EVALUATED and never masquerade as a pass.
    """

    rows = [dict(position) for position in positions]
    modeled = modeled_inputs or {}
    checks: list[dict[str, Any]] = []
    symbols = {str(row.get("symbol", "")).upper() for row in rows}

    if valuation_complete:
        checks.append(_check("valuation_complete", "Valuation", "PASS", message="All supplied positions have usable weights."))
    else:
        checks.append(
            _check(
                "valuation_complete",
                "Valuation",
                "NOT_EVALUATED",
                message="Compliance is incomplete because one or more positions are unpriced.",
                symbols=unpriced_symbols or [],
                severity="availability",
            )
        )

    maximum = constraints.get("max_instrument_weight")
    if maximum is None:
        checks.append(_check("max_instrument_weight", "Security concentration", "NOT_EVALUATED", message="No maximum security weight is configured.", severity="not_applicable"))
    else:
        limit = float(maximum)
        breaches = [row for row in rows if str(row.get("symbol", "")).upper() != "CASH" and float(row.get("weight", 0)) > limit + 1e-8]
        checks.append(_check("max_instrument_weight", "Security concentration", "BREACH" if breaches else "PASS", message=f"{len(breaches)} position(s) exceed the IPS maximum security weight." if breaches else "All positions are within the IPS maximum security weight.", limit=limit, breaches=breaches))

    sector_limit = constraints.get("max_sector_weight")
    sectors: defaultdict[str, float] = defaultdict(float)
    sector_missing = False
    for row in rows:
        if str(row.get("symbol", "")).upper() == "CASH":
            continue
        sector = row.get("sector")
        if sector:
            sectors[str(sector)] += float(row.get("weight", 0))
        else:
            sector_missing = True
    if sector_limit is None:
        checks.append(_check("max_sector_weight", "Sector concentration", "NOT_EVALUATED", message="No maximum sector weight is configured.", severity="not_applicable"))
    elif sector_missing:
        checks.append(_check("max_sector_weight", "Sector concentration", "NOT_EVALUATED", message="Sector metadata is missing for one or more positions.", limit=float(sector_limit), severity="availability"))
    else:
        limit = float(sector_limit)
        breaches = [{"sector": sector, "weight": weight} for sector, weight in sectors.items() if weight > limit + 1e-8]
        checks.append(_check("max_sector_weight", "Sector concentration", "BREACH" if breaches else "PASS", message=f"{len(breaches)} sector(s) exceed the IPS limit." if breaches else "All sectors are within the IPS maximum weight.", limit=limit, breaches=breaches))

    cash_weight = next((float(row.get("weight", 0)) for row in rows if str(row.get("symbol", "")).upper() == "CASH"), 0.0)
    minimum_cash = constraints.get("min_cash_weight")
    if minimum_cash is None:
        checks.append(_check("min_cash_weight", "Minimum cash", "NOT_EVALUATED", message="No minimum cash weight is configured.", severity="not_applicable"))
    else:
        limit = float(minimum_cash)
        breached = cash_weight + 1e-8 < limit
        checks.append(_check("min_cash_weight", "Minimum cash", "BREACH" if breached else "PASS", message="Cash is below the IPS minimum." if breached else "Cash meets the IPS minimum.", actual=cash_weight, limit=limit))

    maximum_cash = constraints.get("max_cash_weight")
    if maximum_cash is not None:
        limit = float(maximum_cash)
        breached = cash_weight > limit + 1e-8
        checks.append(_check("max_cash_weight", "Maximum cash", "BREACH" if breached else "PASS", message="Cash exceeds the IPS maximum." if breached else "Cash is within the IPS maximum.", actual=cash_weight, limit=limit))

    excluded = {str(value).upper() for value in constraints.get("excluded_instruments", [])}
    allowed = {str(value).upper() for value in constraints.get("allowed_instruments", [])}
    disallowed = sorted(symbol for symbol in symbols - {"CASH"} if symbol in excluded or (allowed and symbol not in allowed))
    checks.append(_check("instrument_eligibility", "Instrument eligibility", "BREACH" if disallowed else "PASS", message=f"Disallowed instruments: {', '.join(disallowed)}." if disallowed else "All positions satisfy the configured symbol eligibility rules.", symbols=disallowed))

    if constraints.get("shariah_only"):
        eligible = [row.get("shariah_eligible") for row in rows if str(row.get("symbol", "")).upper() != "CASH"]
        if not eligible or any(value is None for value in eligible):
            checks.append(_check("shariah_eligibility", "Shariah eligibility", "NOT_EVALUATED", message="Eligibility metadata is incomplete; Shariah compliance cannot be asserted.", severity="availability"))
        else:
            failures = [str(row.get("symbol")) for row in rows if row.get("shariah_eligible") is False]
            checks.append(_check("shariah_eligibility", "Shariah eligibility", "BREACH" if failures else "PASS", message=f"Ineligible instruments: {', '.join(failures)}." if failures else "All positions are marked Shariah eligible.", symbols=failures))
    else:
        checks.append(_check("shariah_eligibility", "Shariah eligibility", "NOT_EVALUATED", message="The IPS does not require Shariah-only holdings.", severity="not_applicable"))

    for code, label, input_key in (
        ("target_beta", "Portfolio beta", "portfolio_beta"),
        ("target_volatility", "Portfolio volatility", "portfolio_volatility"),
    ):
        configured = constraints.get(code)
        if configured is None:
            continue
        actual = modeled.get(input_key)
        if actual is None:
            checks.append(_check(code, label, "NOT_EVALUATED", message=f"{label} requires a modeled input that is unavailable for this portfolio state.", limit=configured, severity="availability"))
            continue
        limit = float(configured)
        breached = float(actual) > limit + 1e-8
        checks.append(_check(code, label, "BREACH" if breached else "PASS", message=f"{label} exceeds the confirmed IPS ceiling." if breached else f"{label} is within the confirmed IPS ceiling.", actual=float(actual), limit=limit, estimator=modeled.get("estimator"), data_cutoff=modeled.get("data_cutoff")))

    configured_budgets = constraints.get("risk_budgets")
    if configured_budgets is not None:
        actual_budgets = modeled.get("risk_contributions")
        if not isinstance(actual_budgets, dict) or not actual_budgets:
            checks.append(_check("risk_budgets", "Risk budget", "NOT_EVALUATED", message="Risk-budget compliance requires modeled security risk contributions.", limit=configured_budgets, severity="availability"))
        else:
            configured_rows = {str(symbol).upper(): float(value) for symbol, value in dict(configured_budgets).items() if str(symbol).upper() != "CASH"}
            budget_total = sum(configured_rows.values())
            tolerance = float(constraints.get("risk_budget_tolerance", 0.05))
            normalized = {symbol: value / budget_total for symbol, value in configured_rows.items()} if budget_total > 0 else {}
            missing = sorted(set(normalized) - {str(symbol).upper() for symbol in actual_budgets})
            if not normalized or missing:
                checks.append(_check("risk_budgets", "Risk budget", "NOT_EVALUATED", message="Configured risk budgets are incomplete for the modeled security universe.", limit=configured_budgets, symbols=missing, severity="availability"))
            else:
                breaches = [
                    {"symbol": symbol, "actual": float(actual_budgets.get(symbol, 0)), "limit": target + tolerance, "target": target}
                    for symbol, target in normalized.items()
                    if float(actual_budgets.get(symbol, 0)) > target + tolerance + 1e-8
                ]
                checks.append(_check("risk_budgets", "Risk budget", "BREACH" if breaches else "PASS", message=f"{len(breaches)} security risk contribution(s) exceed target plus tolerance." if breaches else "Security risk contributions are within configured targets plus tolerance.", limit={"targets": normalized, "tolerance": tolerance}, breaches=breaches, estimator=modeled.get("estimator"), data_cutoff=modeled.get("data_cutoff")))

    liquidity_requirement = constraints.get("liquidity_requirement")
    if liquidity_requirement is not None:
        available_cash = modeled.get("liquid_assets")
        if available_cash is None:
            checks.append(_check("liquidity_requirement", "Liquidity requirement", "NOT_EVALUATED", message="Liquidity compliance requires the current operational cash balance.", limit=float(liquidity_requirement), severity="availability"))
        else:
            limit = float(liquidity_requirement)
            breached = float(available_cash) + 1e-8 < limit
            checks.append(_check("liquidity_requirement", "Liquidity requirement", "BREACH" if breached else "PASS", message="Operational cash is below the confirmed near-term liquidity requirement." if breached else "Operational cash covers the confirmed near-term liquidity requirement.", actual=float(available_cash), limit=limit, unit="PKR", data_cutoff=modeled.get("data_cutoff")))

    breaches = [check for check in checks if check["status"] == "BREACH"]
    # A visible non-applicable check is explanatory, not a missing-data failure.
    not_evaluated = [check for check in checks if check["status"] == "NOT_EVALUATED" and check["severity"] == "availability"]
    unavailable = [check for check in not_evaluated if check["severity"] == "availability"]
    overall_status = "BREACH" if breaches else "NOT_EVALUATED" if unavailable else "PASS"
    return {
        "ips_version_id": ips_version_id,
        "context": context,
        "status": overall_status,
        "compliant": overall_status == "PASS",
        "checks": checks,
        "violations": breaches,
        "not_evaluated": not_evaluated,
    }
