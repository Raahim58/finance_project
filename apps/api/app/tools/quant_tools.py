from app.services.workstation_service import portfolio_quant
from app.tools.portfolio_tools import PortfolioInput
from app.tools.registry import ToolDefinition, ToolRegistry


def _quant(db, user, payload: PortfolioInput):
    return portfolio_quant(db, user, payload.portfolio_id)


def register_quant_tools(registry: ToolRegistry) -> None:
    registry.register(ToolDefinition("quant.portfolio", "1.0", "Reproducible portfolio risk and performance metrics", PortfolioInput, "portfolio:read", True, False, 15, "medium", _quant))
