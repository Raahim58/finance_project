import json

from pydantic import BaseModel, Field
from sqlalchemy import select

from app.models.workstation import Instrument, PortfolioIPSVersion

from app.services.portfolio_service import get_portfolio_performance, get_portfolio_summary
from app.services.workstation_service import ips_compliance, list_scenario_runs
from app.tools.registry import ToolDefinition, ToolRegistry, tool_result


class PortfolioInput(BaseModel):
    portfolio_id: str


class PortfolioPerformanceInput(PortfolioInput):
    limit: int = Field(default=365, ge=2, le=5000)


def portfolio_source(portfolio_id, data, method):
    """Internal references identify delivered private evidence without public URLs."""
    return {
        "source_name": "Stored portfolio analysis",
        "record_type": "portfolio",
        "record_id": portfolio_id,
        "calculation_method": method,
        "data_cutoff": data.get("data_cutoff") or data.get("data_freshness_date"),
        "run_id": data.get("run_id"),
        "price_provenance": data.get("price_provenance") or [
            {key: row.get(key) for key in ("symbol", "data_source", "latest_price_date", "artifact_id", "quality_status")}
            for row in data.get("holdings", [])
        ],
    }


def _summary(db, user, payload: PortfolioInput):
    data = get_portfolio_summary(db, user, payload.portfolio_id).model_dump(mode="json")
    holdings = data.get("holdings", [])
    instruments = {row.symbol: row.id for row in db.scalars(
        select(Instrument).where(Instrument.symbol.in_([row["symbol"] for row in holdings]))
    )}
    for holding in holdings:
        holding["instrument_id"] = instruments.get(holding["symbol"])
    return tool_result("ok", data,
                       sources=[portfolio_source(payload.portfolio_id, data, "stored_holdings_and_database_prices")],
                       returned=len(holdings), remaining=0)


def _performance(db, user, payload: PortfolioPerformanceInput):
    points = get_portfolio_performance(db, user, payload.portfolio_id, payload.limit)
    data = {
        "portfolio_id": payload.portfolio_id,
        "points": [point.model_dump(mode="json") for point in points],
    }
    data["data_cutoff"] = points[-1].value_date if points else None
    return tool_result("ok" if points else "missing", data,
                       sources=[portfolio_source(payload.portfolio_id, data, "ledger_time_weighted_return")],
                       returned=len(points), remaining=0)


def _ips(db, user, payload: PortfolioInput):
    data = ips_compliance(db, user, payload.portfolio_id, persist_analysis=False)
    version = db.get(PortfolioIPSVersion, data["ips_version_id"]) if data.get("ips_version_id") else None
    if version is not None and version.portfolio_id != payload.portfolio_id:
        raise ValueError("Selected IPS does not belong to portfolio")
    constraints = json.loads(version.constraints_json or "{}") if version else {}
    inputs = constraints.get("objective_inputs", {})
    method = constraints.get("required_return_method", {})
    data["mandate"] = {
        "available": version is not None,
        "ips_version_id": version.id if version else None,
        "version": version.version if version else None,
        "goal": constraints.get("goal"),
        "horizon_years": inputs.get("horizon_years"),
        "required_return": version.required_return if version else None,
        "required_return_analysis": {
            "available": version is not None and version.required_return is not None,
            "basis": method, "assumptions": inputs,
            "meaning": "required annual return, not a forecast",
        },
        "constraints": constraints,
        "risk_budget_targets": constraints.get("risk_budgets"),
        "risk_budget_tolerance": constraints.get("risk_budget_tolerance"),
        "risk_budget_unit": "fraction_of_portfolio_risk",
    }
    return tool_result(
        "ok", data, sources=[{
            "source_name": "Selected portfolio IPS and compliance",
            "record_type": "ips_version", "record_id": data.get("ips_version_id"),
            "portfolio_id": payload.portfolio_id,
            "version": version.version if version else None,
            "confirmed_at": version.confirmed_at if version else None,
            "calculation_method": "evaluate_ips_constraints",
            "data_cutoff": data.get("data_cutoff"), "price_provenance": data.get("price_provenance", []),
        }], returned=1, remaining=0
    )


def _scenario_history(db, user, payload: PortfolioInput):
    rows = list_scenario_runs(db, user, payload.portfolio_id)
    return tool_result(
        "ok" if rows else "missing", {"history": rows}, returned=len(rows), remaining=0
    )


def register_portfolio_tools(registry: ToolRegistry) -> None:
    registry.register(
        ToolDefinition(
            "portfolio.summary",
            "1.0",
            "User-owned holdings with resolved instrument IDs, cash, valuation, source metadata and freshness",
            PortfolioInput,
            "portfolio:read",
            True,
            False,
            5,
            "low",
            _summary,
        )
    )
    registry.register(
        ToolDefinition(
            "portfolio.performance",
            "1.0",
            "Cash-flow-adjusted ledger performance history",
            PortfolioPerformanceInput,
            "portfolio:read",
            True,
            False,
            10,
            "medium",
            _performance,
        )
    )
    registry.register(
        ToolDefinition(
            "ips.compliance",
            "1.0",
            "Selected IPS mandate, goal, horizon, required-return basis, risk-budget targets and current compliance",
            PortfolioInput,
            "portfolio:read",
            True,
            False,
            8,
            "low",
            _ips,
        )
    )
    registry.register(
        ToolDefinition(
            "scenario.history",
            "1.0",
            "Recorded scenario runs with stressed PnL and compliance for a portfolio",
            PortfolioInput,
            "portfolio:read",
            True,
            False,
            8,
            "low",
            _scenario_history,
        )
    )
