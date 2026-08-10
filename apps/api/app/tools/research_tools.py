from pydantic import BaseModel, Field

from app.schemas.rag import RagSearchRequest
from app.services.rag_service import search_rag
from app.tools.registry import ToolDefinition, ToolRegistry


class ResearchInput(BaseModel):
    query: str = Field(min_length=1)
    portfolio_id: str | None = None
    symbols: list[str] | None = None
    limit: int = Field(default=5, ge=1, le=10)


def _search(db, user, payload: ResearchInput):
    result = search_rag(db, user, RagSearchRequest(**payload.model_dump()))
    return result.model_dump(mode="json")


def register_research_tools(registry: ToolRegistry) -> None:
    registry.register(ToolDefinition("research.search", "1.0", "Ownership-filtered document retrieval with page citations", ResearchInput, "research:read", True, False, 10, "medium", _search))
