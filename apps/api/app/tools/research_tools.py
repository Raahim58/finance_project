import hashlib
import json
from datetime import date, datetime

from pydantic import BaseModel, Field, model_validator

from app.schemas.rag import RagSearchRequest
from app.models.workstation import Instrument
from app.schemas.intelligence_context import (
    ContextScope,
    ContextSectionName,
    IntelligenceContextRequest,
)
from app.services.context_builder import build_intelligence_context
from app.services.event_intelligence_service import list_normalized_events
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
    sections: list[ContextSectionName] = Field(min_length=1, max_length=1)
    period_start: date | None = None
    period_end: date | None = None
    cursor: str | None = Field(default=None, pattern=r"^[0-9]+$")
    limit: int = Field(default=25, ge=1, le=50)
    sector_comparison_limit: int = Field(default=0, ge=0, le=20)

    @model_validator(mode="after")
    def validate_period(self):
        if self.period_start and self.period_end and self.period_end < self.period_start:
            raise ValueError("period_end must be on or after period_start")
        return self


class EventInput(BaseModel):
    entity_key: str | None = None
    period_start: date | None = None
    period_end: date | None = None
    cursor: str | None = Field(default=None, pattern=r"^[0-9]+$")
    limit: int = Field(default=5, ge=1, le=20)

    @model_validator(mode="after")
    def validate_period(self):
        if self.period_start and self.period_end and self.period_end < self.period_start:
            raise ValueError("period_end must be on or after period_start")
        return self


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


def _date_value(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _event_source(source: dict) -> dict:
    identity = json.dumps(source, default=str, sort_keys=True, separators=(",", ":"))
    return {
        "id": f"event-source-{hashlib.sha256(identity.encode()).hexdigest()[:24]}",
        "source_name": source.get("source_name") or "Event source",
        "source_url": source.get("source_url"),
        "document_id": source.get("document_id"),
        "published_at": source.get("published_at"),
    }


def _normalize_event(event: dict, entity_key: str | None) -> tuple[dict, list[dict]]:
    row = dict(event)
    raw_sources = row.pop("evidence", None)
    if raw_sources is None:
        raw_sources = row.pop("sources", [])
    sources = [_event_source(item) for item in raw_sources]
    row["source_refs"] = [item["id"] for item in sources]
    subjects = row.get("subjects")
    if entity_key and isinstance(subjects, list):
        selected = [
            item
            for item in subjects
            if str(item.get("subject_key") or "").upper() == entity_key.upper()
        ]
        row["subjects"] = selected
        row["subject_coverage"] = {
            "returned": len(selected),
            "total": len(subjects),
            "filter": entity_key.upper(),
        }
    return row, sources


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
    offset = int(payload.cursor or 0)
    requested_limit = min(100, offset + payload.limit + 1)
    context = build_intelligence_context(
        db,
        user,
        IntelligenceContextRequest(
            symbol=instrument.symbol,
            scope=ContextScope.COMPANY_INTELLIGENCE,
            sections=requested,
            event_limit=requested_limit,
            sector_comparison_limit=payload.sector_comparison_limit,
        ),
    )
    section = context.sections[requested[0].value].model_dump(mode="json")
    section_name = requested[0]
    all_sources = list(section["evidence"])
    continuation = None
    remaining = 0
    page_count = None
    if section_name == ContextSectionName.COMPANY_FACTS:
        data = section.get("data") or {}
        facts = data.get("fundamentals") or []
        filtered = []
        for fact in facts:
            period = _date_value(fact.get("period_end"))
            if payload.period_start and (period is None or period < payload.period_start):
                continue
            if payload.period_end and (period is None or period > payload.period_end):
                continue
            filtered.append(fact)
        selected = filtered[offset : offset + payload.limit]
        page_count = len(selected)
        data["fundamentals"] = selected
        section["data"] = data
        selected_ids = {str(item.get("id")) for item in selected}
        all_sources = [
            item
            for item in all_sources
            if any(identifier in str(item.get("underlying_id")) for identifier in selected_ids)
        ]
        remaining = max(0, len(filtered) - offset - len(selected))
        continuation = str(offset + len(selected)) if remaining else None
    elif section_name == ContextSectionName.EVENTS:
        fetched = list_normalized_events(
            db,
            subject_type="instrument",
            subject_key=instrument.symbol,
            view="material",
            occurred_start=payload.period_start,
            occurred_end=payload.period_end,
            offset=offset,
            limit=payload.limit + 1,
        )
        event_sources = []
        selected = []
        for event in fetched[: payload.limit]:
            normalized, sources = _normalize_event(event, instrument.symbol)
            selected.append(normalized)
            event_sources.extend(sources)
        page_count = len(selected)
        selected_refs = {ref for item in selected for ref in item.get("source_refs", [])}
        all_sources = [item for item in event_sources if item["id"] in selected_refs]
        section["data"] = selected
        has_more = len(fetched) > len(selected)
        continuation = str(offset + len(selected)) if has_more else None
        remaining = None if has_more else 0
    section["evidence_refs"] = [
        source.get("evidence_id") or source.get("id") for source in all_sources
    ]
    section.pop("evidence", None)
    sections = [section]
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
    for source in all_sources:
        source_id = source.get("evidence_id") or source.get("id")
        if source_id not in seen:
            seen.add(source_id)
            sources.append(source)
    returned = sum(section["state"] not in {"missing", "not_evaluated"} for section in sections)
    result_count = returned if page_count is None else page_count
    return tool_result(
        "ok" if returned else "missing",
        {
            "instrument_id": instrument.id,
            "symbol": instrument.symbol,
            "sections": sections,
            "measurements": measurements,
        },
        sources=sources,
        returned=result_count,
        remaining=remaining,
        continuation=continuation,
    )


def _events(db, _user, payload: EventInput):
    offset = int(payload.cursor or 0)
    fetched = list_events(
        db,
        entity_key=payload.entity_key,
        occurred_start=payload.period_start,
        occurred_end=payload.period_end,
        offset=offset,
        limit=payload.limit + 1,
    )
    selected = fetched[: payload.limit]
    events = []
    sources = []
    for event in selected:
        normalized, event_sources = _normalize_event(event, payload.entity_key)
        events.append(normalized)
        sources.extend(event_sources)
    has_more = len(fetched) > len(selected)
    return tool_result(
        "ok" if events else "missing",
        {"events": events},
        sources=list({item["id"]: item for item in sources}.values()),
        returned=len(events),
        remaining=None if has_more else 0,
        continuation=str(offset + len(events)) if has_more else None,
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
            "One explicit company financial, market-risk, sector, macro, or event section with period filters and pagination",
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
