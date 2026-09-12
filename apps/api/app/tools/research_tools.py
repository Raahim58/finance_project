import json

from pydantic import BaseModel, Field

from app.schemas.rag import RagSearchRequest
from app.models.workstation import Instrument
from app.schemas.intelligence_context import (
    ContextScope,
    ContextSectionName,
    IntelligenceContextRequest,
)
from app.services.context_builder import build_intelligence_context
from app.services.rag_service import search_rag
from app.services.research_service import list_events, search_instruments
from app.tools.registry import ToolDefinition, ToolRegistry, tool_result


class ResearchInput(BaseModel):
    query: str = Field(min_length=1)
    portfolio_id: str | None = None
    symbols: list[str] | None = None
    limit: int = Field(default=5, ge=1, le=10)


class CompanySectionsInput(BaseModel):
    instrument_id: str
    sections: list[ContextSectionName] = Field(min_length=1, max_length=5)


class EventInput(BaseModel):
    entity_key: str | None = None
    limit: int = Field(default=20, ge=1, le=100)


class InstrumentSearchInput(BaseModel):
    query: str = Field(min_length=1, max_length=120)
    limit: int = Field(default=10, ge=1, le=20)


def _search(db, user, payload: ResearchInput):
    result = search_rag(db, user, RagSearchRequest(**payload.model_dump()))
    body = result.model_dump(mode="json")
    sources = [item.model_dump(mode="json") for item in result.citations]
    chunks = []
    for item in body["chunks"]:
        chunk = dict(item)
        citation = chunk.pop("citation")
        chunk.pop("source_url", None)
        chunk["source_ref"] = citation["id"]
        chunks.append(chunk)
    return tool_result(
        "ok" if result.chunks else "missing",
        {
            "chunks": chunks,
            "audit": body["audit"],
            "disambiguation": body["disambiguation"],
        },
        sources=sources,
        returned=len(result.chunks),
        remaining=None,
    )


def _company_sections(db, user, payload: CompanySectionsInput):
    allowed = {
        ContextSectionName.COMPANY_FACTS,
        ContextSectionName.MARKET_RISK,
        ContextSectionName.SECTOR,
        ContextSectionName.MACRO,
        ContextSectionName.EVENTS,
    }
    requested = tuple(dict.fromkeys(payload.sections))
    if set(requested) - allowed:
        return tool_result(
            "invalid_arguments",
            error={"code": "unsupported_company_section", "fields": ["sections"]},
        )
    instrument = db.get(Instrument, payload.instrument_id)
    if instrument is None:
        return tool_result("missing", error={"code": "instrument_not_found"})
    context = build_intelligence_context(
        db,
        user,
        IntelligenceContextRequest(
            symbol=instrument.symbol,
            scope=ContextScope.COMPANY_INTELLIGENCE,
            sections=requested,
        ),
    )
    sections = [context.sections[name.value].model_dump(mode="json") for name in requested]
    measurements = []
    for section in sections:
        encoded = json.dumps(section, separators=(",", ":"), default=str).encode()
        measurements.append(
            {
                "section": section["name"],
                "serialized_bytes": len(encoded),
                "estimated_tokens": (len(encoded) + 3) // 4,
                "size_kind": "estimate",
                "elapsed_ms": context.receipt.section_duration_ms[section["name"]],
            }
        )
    sources = []
    seen = set()
    for section in sections:
        for source in section["evidence"]:
            if source["evidence_id"] not in seen:
                seen.add(source["evidence_id"])
                sources.append(source)
    returned = sum(section["state"] not in {"missing", "not_evaluated"} for section in sections)
    return tool_result(
        "ok" if returned else "missing",
        {
            "instrument_id": instrument.id,
            "symbol": instrument.symbol,
            "sections": sections,
            "measurements": measurements,
        },
        sources=sources,
        returned=returned,
        remaining=len(sections) - returned,
    )


def _events(db, _user, payload: EventInput):
    events = list_events(db, entity_key=payload.entity_key, limit=payload.limit)
    return tool_result(
        "ok" if events else "missing",
        {"events": events},
        returned=len(events),
        remaining=None,
    )


def _instruments(db, _user, payload: InstrumentSearchInput):
    rows = [
        item.model_dump(mode="json")
        for item in search_instruments(db, payload.query, limit=payload.limit)
    ]
    return tool_result(
        "ok" if rows else "missing",
        {"instruments": rows},
        returned=len(rows),
        remaining=None,
    )


def register_research_tools(registry: ToolRegistry) -> None:
    registry.register(
        ToolDefinition(
            "research.search",
            "1.0",
            "Ownership-filtered document retrieval with page citations",
            ResearchInput,
            "research:read",
            True,
            False,
            10,
            "medium",
            _search,
        )
    )
    registry.register(
        ToolDefinition(
            "research.company_sections",
            "1.0",
            "Explicit company financial, market-risk, sector, macro, or event sections",
            CompanySectionsInput,
            "research:read",
            True,
            False,
            12,
            "medium",
            _company_sections,
        )
    )
    registry.register(
        ToolDefinition(
            "research.events",
            "1.0",
            "Observed events with source links and entity filters",
            EventInput,
            "research:read",
            True,
            False,
            8,
            "low",
            _events,
        )
    )
    registry.register(
        ToolDefinition(
            "research.instruments",
            "1.0",
            "Resolve a company name or PSX symbol to structured instrument IDs",
            InstrumentSearchInput,
            "research:read",
            True,
            False,
            5,
            "low",
            _instruments,
        )
    )
