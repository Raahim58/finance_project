from pydantic import BaseModel, Field

from app.services.portfolio_service import get_portfolio_performance, get_portfolio_summary
from app.services.workstation_service import ips_compliance, list_scenario_runs
from app.tools.registry import ToolDefinition, ToolRegistry, tool_result


class PortfolioInput(BaseModel):
    portfolio_id: str


class PortfolioPerformanceInput(PortfolioInput):
    limit: int = Field(default=365, ge=2, le=5000)


def _summary(db, user, payload: PortfolioInput):
    data = get_portfolio_summary(db, user, payload.portfolio_id).model_dump(mode="json")
    return tool_result("ok", data, returned=len(data.get("holdings", [])), remaining=0)


def _performance(db, user, payload: PortfolioPerformanceInput):
    points = get_portfolio_performance(db, user, payload.portfolio_id, payload.limit)
    data = {
        "portfolio_id": payload.portfolio_id,
        "points": [point.model_dump(mode="json") for point in points],
    }
    return tool_result("ok" if points else "missing", data, returned=len(points), remaining=0)


def _ips(db, user, payload: PortfolioInput):
    return tool_result(
        "ok", ips_compliance(db, user, payload.portfolio_id), returned=1, remaining=0
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
            "User-owned holdings, cash, valuation, and freshness",
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
            "Confirmed IPS constraints and current compliance violations",
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
