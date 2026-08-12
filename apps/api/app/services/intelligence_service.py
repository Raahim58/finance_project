"""Intelligence V1 orchestration.

This module owns no analytical formulas or portfolio truth. It composes canonical
market/research data, the immutable ledger view, quant comparison, scenario mapping,
IPS compliance, and existing proposal persistence around one security decision.
"""
from __future__ import annotations

from decimal import Decimal

import numpy as np
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.quant import optimize
from app.models.user import User
from app.models.workstation import Instrument
from app.schemas.intelligence import CandidateEvaluationRequest, SaveCandidateProposalRequest
from app.schemas.portfolio import AllocationItemInput, AllocationSetCreate
from app.schemas.workstation import PortfolioComparisonRequest
from app.services.compliance_service import evaluate_ips_constraints
from app.services.decision_analytics_service import _market_inputs, compare_portfolio
from app.services.portfolio_service import create_allocation_set, get_portfolio_exposure, get_portfolio_summary
from app.services.regime_service import macro_regime
from app.services.research_service import company_overview
from app.services.scenario_service import list_scenario_templates, resolve_shock
from app.services.workstation_service import _selected_ips_constraints, ips_compliance


def _instrument(db: Session, symbol: str) -> Instrument:
    row = db.scalar(select(Instrument).where(Instrument.symbol == symbol.upper()))
    if row is None:
        raise HTTPException(status_code=404, detail="Instrument not found")
    return row


def _portfolio_context(db: Session, user: User, portfolio_id: str, instrument: Instrument) -> dict[str, object]:
    summary = get_portfolio_summary(db, user, portfolio_id)
    exposure = get_portfolio_exposure(db, user, portfolio_id)
    compliance = ips_compliance(db, user, portfolio_id)
    total = float(summary.total_value)
    holding = next((row for row in summary.holdings if row.symbol == instrument.symbol), None)
    current_weight = float(holding.market_value) / total if holding and total else 0.0
    sector_weight = next((float(row.weight_percent) / 100 for row in exposure.by_sector if row.sector == instrument.sector), 0.0)
    constraints = _selected_ips_constraints(db, summary.portfolio)
    sector_limit = constraints.get("max_sector_weight")
    position_limit = constraints.get("max_instrument_weight")
    correlation: dict[str, object] = {"available": False, "reason": "At least 31 aligned observations across the candidate and holdings are required."}
    try:
        _, symbols, days, returns, _covariance, _expected, *_ = _market_inputs(db, user, portfolio_id, [instrument.symbol])
        matrix = np.corrcoef(returns, rowvar=False)
        index = symbols.index(instrument.symbol)
        correlation = {
            "available": True,
            "data_cutoff": days[-1],
            "with_holdings": {symbol: float(matrix[index, offset]) for offset, symbol in enumerate(symbols) if symbol != instrument.symbol},
            "average_with_holdings": float(np.mean([matrix[index, offset] for offset, symbol in enumerate(symbols) if symbol != instrument.symbol])),
            "estimator": "aligned_canonical_daily_returns",
        }
    except (HTTPException, ValueError):
        pass
    return {
        "portfolio": {"id": summary.portfolio.id, "name": summary.portfolio.name, "value": total, "data_cutoff": summary.data_freshness_date, "source": summary.data_source},
        "ownership": {"weight": current_weight, "market_value": float(holding.market_value) if holding else 0.0, "quantity": float(holding.quantity) if holding else 0.0},
        "sector_exposure": {"sector": instrument.sector, "current_weight": sector_weight, "limit": float(sector_limit) if sector_limit is not None else None, "headroom": max(0.0, float(sector_limit) - sector_weight) if sector_limit is not None else None},
        "position_headroom": max(0.0, float(position_limit) - current_weight) if position_limit is not None else None,
        "correlation": correlation,
        "compliance": compliance,
    }


def security_intelligence(db: Session, user: User, symbol: str, portfolio_id: str | None = None) -> dict[str, object]:
    instrument = _instrument(db, symbol)
    research = company_overview(db, user, instrument.id)
    regime = macro_regime(db, user, portfolio_id)
    portfolio = _portfolio_context(db, user, portfolio_id, instrument) if portfolio_id else None
    missing = []
    if not research.get("market"):
        missing.append("Current canonical market observation is unavailable.")
    if not research.get("fundamentals"):
        missing.append("Normalized FinancialFact data is unavailable; document text is not substituted for exact values.")
    if not research.get("documents"):
        missing.append("No ownership-visible filings or research documents are available.")
    if regime.get("regime") == "not_evaluated":
        missing.append("Macro regime lacks enough selected structured observations.")
    return {
        "security": research["instrument"],
        "observed_facts": {"market": research.get("market"), "fundamentals": research.get("fundamentals"), "events": research.get("events"), "documents": research.get("documents"), "macro": regime.get("dimensions")},
        "model_outputs": {"market_research": research.get("market_research"), "derived_fundamentals": research.get("derived_fundamentals"), "regime": regime, "portfolio_relevance": portfolio},
        "assumptions": [regime.get("method_note"), "Candidate analytics use aligned canonical daily prices and the confirmed IPS."],
        "ai_interpretation": None,
        "evidence": {"market": research.get("market"), "documents": research.get("documents"), "has_synthetic_data": research.get("has_synthetic_data", False)},
        "missing_data": missing,
    }


def _manual_weights(current: dict[str, float], symbol: str, action: str, target: float) -> dict[str, float]:
    current = dict(current)
    old = current.get(symbol, 0.0)
    if action == "add" and target < old - 1e-8:
        raise HTTPException(status_code=422, detail="Add target must not be below the current weight")
    if action == "reduce" and (old <= 0 or target > old + 1e-8):
        raise HTTPException(status_code=422, detail="Reduce requires an owned position and a target at or below its current weight")
    if action == "remove":
        target = 0.0
    delta = target - old
    current[symbol] = target
    if delta > 0:
        donors = [key for key, value in current.items() if key != symbol and value > 0]
        available = sum(current[key] for key in donors)
        if delta > available + 1e-8:
            raise HTTPException(status_code=422, detail="Candidate target exceeds available portfolio capital")
        for key in donors:
            current[key] -= delta * current[key] / available
    elif delta < 0:
        current["CASH"] = current.get("CASH", 0.0) - delta
    return {key: max(0.0, value) for key, value in current.items()}


def _optimizer_weights(db: Session, user: User, portfolio_id: str, symbol: str) -> tuple[dict[str, float], dict[str, object]]:
    portfolio, symbols, days, _returns, covariance, _expected, constraints, *_ = _market_inputs(db, user, portfolio_id, [symbol])
    summary = get_portfolio_summary(db, user, portfolio_id)
    total = float(summary.total_value)
    cash_weight = float(summary.cash_balance) / total if total else 0.0
    risky_share = 1 - cash_weight
    maximum = float(constraints.get("max_instrument_weight", 1.0)) / risky_share if risky_share else 1.0
    upper = [min(1.0, maximum)] * len(symbols)
    instruments = {row.symbol: row for row in db.scalars(select(Instrument).where(Instrument.symbol.in_(symbols)))}
    linear = []
    if constraints.get("max_sector_weight") is not None and risky_share:
        for sector in {row.sector or "Unknown" for row in instruments.values()}:
            linear.append((np.asarray([1.0 if (instruments.get(item) and (instruments[item].sector or "Unknown") == sector) else 0.0 for item in symbols]), float(constraints["max_sector_weight"]) / risky_share, f"sector:{sector}"))
    result = optimize(covariance, objective="minimum_variance", lower_bounds=[0.0] * len(symbols), upper_bounds=upper, linear_upper_bounds=linear)
    if result.status != "optimal":
        raise HTTPException(status_code=422, detail={"message": "Candidate optimizer could not find an IPS-feasible allocation", "diagnostics": result.diagnostics})
    weights = {item: float(weight) * risky_share for item, weight in zip(symbols, result.weights, strict=True)}
    weights["CASH"] = cash_weight
    return weights, {"objective": "minimum_variance", "data_cutoff": days[-1], "diagnostics": result.diagnostics, "cash_weight_held_constant": cash_weight, "constraints": ["long_only", "max_instrument_weight", "max_sector_weight when configured"]}


def _stress(weights: dict[str, float], instruments: dict[str, Instrument], constraints: dict[str, object], ips_version_id: str | None, suggested: list[str]) -> list[dict[str, object]]:
    template_ids = list(dict.fromkeys([*suggested, "psx_drawdown", "banking_stress"]))[:3]
    templates = {str(item["id"]): item for item in list_scenario_templates()}
    rows = []
    for template_id in template_ids:
        template = templates.get(template_id)
        if not template:
            continue
        shocks = {}
        for symbol, weight in weights.items():
            if symbol == "CASH":
                shocks[symbol] = 0.0
                continue
            instrument = instruments[symbol]
            shock, mappings = resolve_shock(instrument, {}, dict(template["sector_shocks"]), dict(template["factor_shocks"]))
            if not mappings:
                shock = float(template.get("fallback_security_shock", 0.0))
            shocks[symbol] = shock
        portfolio_return = sum(weights.get(symbol, 0.0) * shock for symbol, shock in shocks.items())
        denominator = 1 + portfolio_return
        stressed = {symbol: weights[symbol] * (1 + shocks[symbol]) / denominator if denominator else 0.0 for symbol in weights}
        compliance = evaluate_ips_constraints(constraints, [{"symbol": symbol, "weight": weight, "sector": "Cash" if symbol == "CASH" else instruments[symbol].sector} for symbol, weight in stressed.items()], ips_version_id=ips_version_id, context="candidate_stressed")
        rows.append({"id": template_id, "name": template["name"], "return": portfolio_return, "shocks": shocks, "compliance": compliance, "assumption": template["description"], "version": template["version"]})
    return rows


def evaluate_candidate(db: Session, user: User, symbol: str, payload: CandidateEvaluationRequest) -> dict[str, object]:
    instrument = _instrument(db, symbol)
    summary = get_portfolio_summary(db, user, payload.portfolio_id)
    total = float(summary.total_value)
    current = {row.symbol: float(row.market_value) / total if total else 0.0 for row in summary.holdings}
    current["CASH"] = float(summary.cash_balance) / total if total else 0.0
    optimizer_context = None
    if payload.sizing == "optimizer":
        if payload.action != "add":
            raise HTTPException(status_code=422, detail="Optimizer sizing is available for add evaluations; reduce/remove use explicit targets")
        proposed, optimizer_context = _optimizer_weights(db, user, payload.portfolio_id, instrument.symbol)
    else:
        proposed = _manual_weights(current, instrument.symbol, payload.action, float(payload.target_weight or 0.0))
    comparison = compare_portfolio(db, user, payload.portfolio_id, PortfolioComparisonRequest(target_weights=proposed, label=f"{payload.action.title()} {instrument.symbol}"))
    portfolio = summary.portfolio
    constraints = _selected_ips_constraints(db, portfolio)
    instruments = {row.symbol: row for row in db.scalars(select(Instrument).where(Instrument.symbol.in_([key for key in proposed if key != "CASH"])))}
    regime = macro_regime(db, user, payload.portfolio_id)
    current_stress = _stress(current, instruments, constraints, portfolio.selected_ips_version_id, list(regime.get("suggested_scenario_ids", [])))
    proposed_stress = _stress(proposed, instruments, constraints, portfolio.selected_ips_version_id, list(regime.get("suggested_scenario_ids", [])))
    current_weight, proposed_weight = current.get(instrument.symbol, 0.0), proposed.get(instrument.symbol, 0.0)
    construction_assumption = "Minimum-variance optimizer held the current cash weight constant." if optimizer_context else "Manual additions are funded pro rata from every other positive portfolio weight, including cash; reductions and removals are allocated to cash."
    return {
        "candidate": {"symbol": instrument.symbol, "action": payload.action, "sizing": payload.sizing, "current_weight": current_weight, "proposed_weight": proposed_weight},
        "comparison": comparison,
        "stress": {"current": current_stress, "proposed": proposed_stress},
        "optimizer": optimizer_context,
        "decision_explanation": {
            "improved": [row for row in comparison["trade_offs"] if row["direction"] == "IMPROVED"],
            "deteriorated": [row for row in comparison["trade_offs"] if row["direction"] == "WORSENED"],
            "sizing": f"{instrument.symbol} is sized at {proposed_weight:.2%} by the recorded {optimizer_context['objective']} objective and confirmed bounds." if optimizer_context else f"The user-specified sandbox target is {proposed_weight:.2%}.",
            "assumptions": {**comparison["assumptions"], "candidate_construction": construction_assumption},
            "main_downside_scenarios": sorted(proposed_stress, key=lambda row: float(row["return"]))[:2],
        },
        "ledger_mutated": False,
        "warnings": comparison["warnings"],
    }


def save_candidate_proposal(db: Session, user: User, symbol: str, payload: SaveCandidateProposalRequest):
    evaluation = evaluate_candidate(db, user, symbol, payload)
    weights = evaluation["comparison"]["proposed_weights"]
    summary = get_portfolio_summary(db, user, payload.portfolio_id)
    allocation = create_allocation_set(db, user, payload.portfolio_id, AllocationSetCreate(kind="sandbox", base_value=Decimal(str(summary.total_value)), assumptions={"intelligence_v1": True, "label": payload.label, "candidate": evaluation["candidate"], "decision_explanation": evaluation["decision_explanation"], "stress": evaluation["stress"]}, items=[AllocationItemInput(symbol=key, target_weight=Decimal(str(value)), is_cash=key == "CASH") for key, value in weights.items()]))
    return {"proposal": allocation, "evaluation": evaluation, "ledger_mutated": False}
