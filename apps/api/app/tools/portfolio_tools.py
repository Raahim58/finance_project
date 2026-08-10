from pydantic import BaseModel

from app.services.portfolio_service import get_portfolio_summary
from app.tools.registry import ToolDefinition, ToolRegistry


class PortfolioInput(BaseModel):
    portfolio_id: str


def _summary(db, user, payload: PortfolioInput):
    return get_portfolio_summary(db, user, payload.portfolio_id).model_dump(mode="json")


def register_portfolio_tools(registry: ToolRegistry) -> None:
    registry.register(ToolDefinition("portfolio.summary", "1.0", "User-owned holdings, cash, valuation, and freshness", PortfolioInput, "portfolio:read", True, False, 5, "low", _summary))
