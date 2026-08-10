from datetime import date

from pydantic import BaseModel, Field

from app.services.market_service import get_market_freshness
from app.services.research_service import list_macro_series, macro_releases, market_series
from app.tools.registry import ToolDefinition, ToolRegistry


class EmptyInput(BaseModel):
    pass


class MarketSeriesInput(BaseModel):
    instrument_id: str
    start: date | None = None
    end: date | None = None


class MacroInput(BaseModel):
    series_id: str | None = None


def _freshness(db, _user, _payload: EmptyInput):
    return get_market_freshness(db).model_dump(mode="json")


def _series(db, _user, payload: MarketSeriesInput):
    return market_series(db, payload.instrument_id, payload.start, payload.end)


def _macro(db, _user, payload: MacroInput):
    return {"series": list_macro_series(db), "releases": macro_releases(db, payload.series_id)}


def register_market_tools(registry: ToolRegistry) -> None:
    registry.register(ToolDefinition("market.freshness", "1.0", "Current structured market-data freshness and provider status", EmptyInput, "market:read", True, False, 5, "low", _freshness))
    registry.register(ToolDefinition("market.series", "1.0", "Canonical OHLCV history with observation provenance", MarketSeriesInput, "market:read", True, False, 10, "medium", _series))
    registry.register(ToolDefinition("macro.releases", "1.0", "Observed macro series and effective-dated releases", MacroInput, "market:read", True, False, 10, "medium", _macro))
