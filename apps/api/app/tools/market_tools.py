from pydantic import BaseModel

from app.services.market_service import get_market_freshness
from app.tools.registry import ToolDefinition, ToolRegistry


class EmptyInput(BaseModel):
    pass


def _freshness(db, _user, _payload: EmptyInput):
    return get_market_freshness(db).model_dump(mode="json")


def register_market_tools(registry: ToolRegistry) -> None:
    registry.register(ToolDefinition("market.freshness", "1.0", "Current structured market-data freshness and provider status", EmptyInput, "market:read", True, False, 5, "low", _freshness))
