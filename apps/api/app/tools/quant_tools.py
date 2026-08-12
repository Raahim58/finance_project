from pydantic import BaseModel

from app.services.decision_analytics_service import risk_budget_analysis
from app.services.workstation_service import portfolio_quant, security_quant
from app.tools.portfolio_tools import PortfolioInput
from app.tools.registry import ToolDefinition, ToolRegistry


def _quant(db, user, payload: PortfolioInput):
    return portfolio_quant(db, user, payload.portfolio_id)


class SecurityInput(BaseModel):
    instrument_id: str


def _security(db, _user, payload: SecurityInput):
    return security_quant(db, payload.instrument_id)


def _risk_budget(db, user, payload: PortfolioInput):
    return risk_budget_analysis(db, user, payload.portfolio_id)


def register_quant_tools(registry: ToolRegistry) -> None:
    registry.register(ToolDefinition("quant.portfolio", "1.0", "Reproducible portfolio risk and performance metrics", PortfolioInput, "portfolio:read", True, False, 15, "medium", _quant))
    registry.register(ToolDefinition("quant.security", "1.0", "Security return and risk metrics from canonical observations", SecurityInput, "market:read", True, False, 10, "medium", _security))
    registry.register(ToolDefinition("quant.risk_budget", "1.0", "Total-capital and risky-sleeve weights with percentage risk contribution per holding", PortfolioInput, "portfolio:read", True, False, 15, "medium", _risk_budget))
