"""Read-only database adapter around arithmetic and existing analytical contracts."""
import hashlib
import json
from datetime import UTC, datetime
from fastapi import HTTPException
from sqlalchemy import or_, select
from app.models.workstation import Instrument
from app.reasoning.allocation import calculate_allocation
from app.schemas.workstation import PortfolioComparisonRequest
from app.services.canonical_market_service import latest_price
from app.services.portfolio_service import get_portfolio_summary
from app.services.workstation_service import _selected_ips_constraints
from app.services.compliance_service import evaluate_ips_constraints, shariah_eligibility
from app.services.context_builder import price_freshness
from app.services.decision_analytics_service import compare_portfolio


def verify_allocation(db, user, portfolio_id, proposal, allowed_ids):
    summary = get_portfolio_summary(db, user, portfolio_id)
    requested = {leg.instrument_id for leg in proposal.legs}
    instruments = list(db.scalars(select(Instrument).where(or_(
        Instrument.symbol.in_([row.symbol for row in summary.holdings]),
        Instrument.id.in_(requested),
    ))))
    by_symbol = {row.symbol: row for row in instruments}
    held = {by_symbol[row.symbol].id: row.quantity for row in summary.holdings if row.symbol in by_symbol}
    requested = {leg.instrument_id for leg in proposal.legs}
    eligible = set(allowed_ids) | set(held)
    if requested - eligible:
        return {"accepted": False, "errors": ["instrument_outside_resolved_scope"]}
    records = {}
    freshness = {}
    now = datetime.now(UTC)
    for row in instruments:
        if row.id not in requested | set(held):
            continue
        price = latest_price(db, row.symbol)
        metadata = json.loads(row.metadata_json or "{}")
        freshness[row.id] = price_freshness(db, price, now)
        records[row.id] = {"symbol": row.symbol, "sector": row.sector,
            "currency": row.currency, "asset_type": row.instrument_type,
            "shariah_eligible": shariah_eligibility(metadata),
            "lot_size": metadata.get("lot_size"), "price": price.close if price else None,
            "source": price.source if price else None,
            "source_url": price.source_url if price else None,
            "artifact_id": price.artifact_id if price else None,
            "artifact_sha256": price.artifact_sha256 if price else None,
            "trade_date": str(price.trade_date) if price else None}
    result = calculate_allocation(proposal, held, summary.cash_balance, records)
    arithmetic_errors = list(result["errors"])
    if not summary.valuation_complete or any(row.symbol not in by_symbol for row in summary.holdings):
        result["errors"].append("incomplete_portfolio_valuation")
    if not summary.portfolio.selected_ips_version_id:
        result["errors"].append("confirmed_ips_missing")
    if any(row["currency"] != summary.portfolio.base_currency for row in records.values()):
        result["errors"].append("currency_conversion_unavailable")
    constraints = _selected_ips_constraints(db, summary.portfolio)
    def positions(weights):
        return [{"symbol": "CASH", "weight": weight} if key == "CASH" else
                {**records[key], "weight": weight} for key, weight in weights.items() if weight > 0]
    for mode in ("current", "proposed"):
        result[mode + "_compliance"] = evaluate_ips_constraints(constraints,
            positions(result[mode + "_weights"]), ips_version_id=summary.portfolio.selected_ips_version_id,
            valuation_complete=summary.valuation_complete,
            modeled_inputs={"liquid_assets": float(result[mode + "_cash"])})
    weights = {("CASH" if key == "CASH" else records[key]["symbol"]): value
               for key, value in result["proposed_weights"].items()}
    metrics = {}
    comparison = None
    try:
        comparison = compare_portfolio(db, user, portfolio_id, PortfolioComparisonRequest(target_weights=weights), persist_analysis=False)
        result["comparison"] = comparison
        result["current_compliance"] = comparison["current_compliance"]
        # Re-evaluate with instrument metadata, which older comparison does not include.
        metrics = {row["key"]: row["proposed"] for row in comparison["metrics"]}
        result["proposed_compliance"] = evaluate_ips_constraints(constraints,
            positions(result["proposed_weights"]), ips_version_id=summary.portfolio.selected_ips_version_id,
            modeled_inputs={"liquid_assets": float(result["proposed_cash"]),
                "portfolio_volatility": metrics.get("volatility"), "portfolio_beta": metrics.get("beta"),
                "risk_contributions": comparison["proposed_risk_contributions"]})
    except (HTTPException, ValueError) as exc:
        result["unavailable_checks"] = ["modeled_return", "risk_contributions"]
        result["analytical_error"] = type(exc).__name__
    compliance = result["proposed_compliance"]
    result["remaining_breaches"] = compliance["violations"]
    if compliance["violations"]:
        result["errors"].append("binding_constraint_breach_remains")
    if compliance["not_evaluated"]:
        result["errors"].append("binding_constraint_check_unavailable")
    result["accepted"] = not result["errors"]
    required = metrics.get("required_return")
    modeled = metrics.get("expected_return")
    feasibility = "unavailable" if required is None or modeled is None else "meets" if modeled >= required else "below"
    freshness_status = (
        "unavailable" if not freshness or any(item["status"] == "unavailable" for item in freshness.values())
        else "stale" if any(item["status"] == "stale" for item in freshness.values()) else "current"
    )
    result["checks"] = {
        "arithmetic_funding": {"status": "rejected" if arithmetic_errors else "accepted", "errors": arithmetic_errors},
        "ips_compliance": {"status": compliance["status"], "violations": compliance["violations"], "not_evaluated": compliance["not_evaluated"]},
        "price_freshness": {"status": freshness_status, "instruments": freshness},
        "modeled_goal": {
            "status": feasibility, "required_return": required, "proposed_modeled_return": modeled,
            "shortfall": max(required - modeled, 0) if required is not None and modeled is not None else None,
            "method": comparison["assumptions"]["expected_return_method"] if comparison else None,
            "unit": "annual_decimal_rate", "guaranteed": False,
        },
    }
    result["evidence_readiness"] = {
        "status": "ready" if freshness_status == "current" and summary.valuation_complete and summary.portfolio.selected_ips_version_id else "insufficient_evidence",
        "actionable_recommendation_eligible": bool(result["accepted"] and freshness_status == "current" and summary.valuation_complete and summary.portfolio.selected_ips_version_id),
        "optimality": "not_established",
    }
    result["evidence_versions"] = records
    result["ips_version_id"] = summary.portfolio.selected_ips_version_id
    result["verification_id"] = hashlib.sha256(json.dumps(result, sort_keys=True, default=str).encode()).hexdigest()
    return result
