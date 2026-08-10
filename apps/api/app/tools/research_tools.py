from pydantic import BaseModel, Field

from app.schemas.rag import RagSearchRequest
from app.services.rag_service import search_rag
from app.services.research_service import company_overview, list_events, search_instruments
from app.services.ingestion_service import refresh_company_research
from app.tools.registry import ToolDefinition, ToolRegistry


class ResearchInput(BaseModel):
    query: str = Field(min_length=1)
    portfolio_id: str | None = None
    symbols: list[str] | None = None
    limit: int = Field(default=5, ge=1, le=10)


class CompanyInput(BaseModel):
    instrument_id: str


class EventInput(BaseModel):
    entity_key: str | None = None
    limit: int = Field(default=20, ge=1, le=100)


class InstrumentSearchInput(BaseModel):
    query: str = Field(min_length=1, max_length=120)
    limit: int = Field(default=10, ge=1, le=20)


class CompanyRefreshInput(BaseModel):
    instrument_id: str
    report_limit: int = Field(default=5, ge=1, le=20)


def _search(db, user, payload: ResearchInput):
    result = search_rag(db, user, RagSearchRequest(**payload.model_dump()))
    return result.model_dump(mode="json")


def _company(db, user, payload: CompanyInput):
    return company_overview(db, user, payload.instrument_id)


def _events(db, _user, payload: EventInput):
    return {"events": list_events(db, payload.entity_key, payload.limit)}


def _instruments(db, _user, payload: InstrumentSearchInput):
    return {"instruments": [item.model_dump(mode="json") for item in search_instruments(db, payload.query, limit=payload.limit)]}


def _refresh_company(db, _user, payload: CompanyRefreshInput):
    return refresh_company_research(db, payload.instrument_id, payload.report_limit)


def register_research_tools(registry: ToolRegistry) -> None:
    registry.register(ToolDefinition("research.search", "1.0", "Ownership-filtered document retrieval with page citations", ResearchInput, "research:read", True, False, 10, "medium", _search))
    registry.register(ToolDefinition("research.company", "1.0", "Company market, fundamental, filing, event, and portfolio context", CompanyInput, "research:read", True, False, 12, "medium", _company))
    registry.register(ToolDefinition("research.events", "1.0", "Observed events with source links and entity filters", EventInput, "research:read", True, False, 8, "low", _events))
    registry.register(ToolDefinition("research.instruments", "1.0", "Resolve a company name or PSX symbol to structured instrument IDs", InstrumentSearchInput, "research:read", True, False, 5, "low", _instruments))
    registry.register(ToolDefinition("research.refresh_company", "1.0", "Acquire and index newly observed official PSX company reports before retrieval", CompanyRefreshInput, "research:refresh", False, False, 30, "high", _refresh_company))
