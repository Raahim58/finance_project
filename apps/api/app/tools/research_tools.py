import hashlib
import json
from datetime import date, datetime

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select

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
    sectors: list[str] | None = Field(default=None, max_length=20)
    topics: list[str] | None = Field(default=None, max_length=20)
    document_types: list[str] | None = Field(default=None, max_length=20)
    date_from: date | None = None
    date_to: date | None = None
    include_broader_context: bool = True
    cursor: str | None = Field(default=None, max_length=6000)
    limit: int = Field(default=5, ge=1, le=10)

    @model_validator(mode='after')
    def check_dates(self):
        if self.date_from and self.date_to and self.date_from>self.date_to:
            raise ValueError('date_from must be on or before date_to')
        return self


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
    query: str | None = Field(default=None, min_length=1, max_length=120)
    entity_key: str | None = None
    period_start: date | None = None
    period_end: date | None = None
    cursor: str | None = Field(default=None, pattern=r"^[0-9]+$")
    limit: int = Field(default=5, ge=1, le=20)

    @model_validator(mode="after")
    def validate_period(self):
        if self.query and self.entity_key:
            raise ValueError("Headline query is for broader events; omit entity_key")
        if self.period_start and self.period_end and self.period_end < self.period_start:
            raise ValueError("period_end must be on or after period_start")
        return self


class InstrumentSearchInput(BaseModel):
    query: str = Field(min_length=1, max_length=120)
    limit: int = Field(default=10, ge=1, le=20)


def _search(db, user, payload: ResearchInput, *, public_only=False):
    from app.services.news_retrieval import search_research_evidence
    from app.models.document import Document
    chosen,citations,coverage=search_research_evidence(db,user,payload,public_only=public_only)
    sources=[item.model_dump(mode='json') for item in citations]
    dates={row.id:row.published_date for row in db.scalars(select(Document).where(Document.id.in_([c.document_id for _,c in chosen])))}
    chunks=[{'id':c.id,'document_id':c.document_id,'group':name,'title':c.citation.title,
        'published_date':str(dates[c.document_id]) if dates.get(c.document_id) else None,
        'text':c.chunk_text,'source_ref':c.citation.id,'document_type':c.document_type,
        'evidence_kind':c.metadata.get('evidence_kind', 'reporting' if c.document_type == 'news' else c.document_type)} for name,c in chosen]
    return tool_result(
        "ok" if chunks else "missing", {"chunks":chunks, "coverage":coverage},
        sources=sources,
        returned=len(chunks),
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
    excerpts = [{"source_ref": source["id"], "text": item["text"]}
                for item, source in zip(raw_sources, sources) if item.get("text")]
    if excerpts:
        row["evidence_excerpts"] = excerpts
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
        from app.services.research_intelligence_service import company_event_page
        page = company_event_page(db, user, instrument, start=payload.period_start,
            end=payload.period_end, offset=offset, limit=payload.limit)
        selected, all_sources = [], []
        for event in page["events"]:
            normalized, sources = _normalize_event(event, instrument.symbol)
            selected.append(normalized)
            all_sources.extend(sources)
        page_count = len(selected)
        section["data"] = selected
        section["as_of"] = max((row["occurred_at"] for row in selected), default=None)
        section["errors"] = []
        section["provenance"] = {**section.get("provenance", {}), "event_coverage": page["coverage"]}
        section["state"] = "stale" if selected and all(row.get("freshness_status") == "stale" for row in selected) else "current" if selected else "missing"
        continuation = page["coverage"]["continuation"]
        remaining = None if page["coverage"]["has_more"] else 0
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


def _events(db, user, payload: EventInput):
    offset = int(payload.cursor or 0)
    if payload.entity_key:
        from app.services.research_intelligence_service import company_event_page, resolve_company
        instrument = resolve_company(db, payload.entity_key)
        page = company_event_page(db, user, instrument, start=payload.period_start,
            end=payload.period_end, offset=offset, limit=payload.limit)
        fetched = page["events"]
        coverage = page["coverage"]
        has_more = coverage["has_more"]
    else:
        # Broad market/geopolitical retrieval has no three-factor or issuer gate.
        arguments = {"entity_key": None, "occurred_start": payload.period_start,
                     "occurred_end": payload.period_end, "offset": offset, "limit": payload.limit + 1}
        if payload.query:
            arguments["query"] = payload.query
        fetched = list_events(db, **arguments)
        has_more = len(fetched) > payload.limit
        fetched = fetched[:payload.limit]
        coverage = {"query": payload.query, "period_start": payload.period_start,
                    "period_end": payload.period_end, "scope": "broader_stored_events",
                    "relationship": "For model analysis; not a stored company exposure match."}
    events, sources = [], []
    for event in fetched:
        normalized, event_sources = _normalize_event(event, payload.entity_key)
        events.append(normalized)
        sources.extend(event_sources)
    return tool_result("ok" if events else "missing", {"events": events, "search_coverage": coverage},
        sources=list({item["id"]: item for item in sources}.values()), returned=len(events),
        remaining=None if has_more else 0,
        continuation=str(offset + len(events)) if has_more else None)


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


class CompanyDigestInput(BaseModel):
    instrument_id: str


def _company_digest(db,user,payload):
    from app.services.company_digest_service import read_digest
    from app.services.research_generation_service import brief_projection
    instrument = db.get(Instrument,payload.instrument_id)
    if instrument is None:
        return tool_result('missing',error={'code':'instrument_not_found'})
    saved = read_digest(db,user,instrument,active=False)
    from app.services.pipeline.briefing import read as read_extra_analysis
    extra=read_extra_analysis(db,symbols=[instrument.symbol],sectors=[instrument.sector] if instrument.sector else None,limit=2)
    snapshot = saved['snapshot']
    if not snapshot and saved.get('prepared_intelligence'):
        import copy
        prepared=copy.deepcopy(saved['prepared_intelligence'])
        sources=[]
        for section in prepared:
            section['source_refs']=[]
            for row in section.get('content',{}).get('evidence',[]):
                identifier=row.get('id') or row.get('statement_id')
                if identifier: row['evidence_refs']=[identifier]
                for field in ('id','statement_id','document_id','source_name','source_url','page_number','version'):
                    row.pop(field,None)
            if section.get('section')=='financial_performance':
                evidence=section.get('content',{}).pop('evidence',[])
                groups={}
                for row in evidence: groups.setdefault(row.get('accounting_basis') or 'unverified',[]).append(row)
                section['content']['reporting_bases']=[{'basis':basis,'facts':facts} for basis,facts in groups.items()]
            for source in section.pop('sources',[]):
                ref=source.get('fact_id') or source.get('statement_id')
                section['source_refs'].append(ref)
                sources.append({'id':ref,**source})
        for row in extra:
            sources.append({k:row[k] for k in ('id','source_name','source_url','title','published_date')})
        analysis=[{'text':row['text'],'classification':'interpretation','source_ref':row['id'],'published_date':row['published_date']} for row in extra]
        return tool_result('ok',{'prepared_intelligence':prepared,'extra_analysis':analysis,'brief_is_current':False,'status':'source_grounded'},sources=sources,returned=len(prepared))
    if not snapshot:
        return tool_result('missing',{'status':saved['status'],'detail':'No saved company digest yet. Use company_sections/search for evidence; page opening can queue preparation.'},returned=0)
    # Map snapshot-local refs to unique execution evidence IDs before packet fusion.
    prefix = 'digest-'+saved['input_hash'][:12]+'-'
    def refs(value):
        if isinstance(value,dict):
            return {k:refs(v) for k,v in value.items()}
        if isinstance(value,list): return [refs(v) for v in value]
        if isinstance(value,str) and value in snapshot['sources']: return prefix+value
        return value
    data = refs(brief_projection(snapshot))
    data['citation_locations'] = data.pop('sources',None)
    # The brief belongs to its own input version, which can differ during a refresh.
    data['brief'] = None
    data['brief_validation_status'] = saved.get('brief_validation_status','reference_only')
    data['interpretation_gap'] = 'Saved AI narrative has not passed source entailment review; answer from supplied facts and excerpts.'
    data['brief_is_current'] = saved['brief_is_current']
    data['snapshot_is_current'] = snapshot.get('input_hash') == saved['input_hash']
    if not data['snapshot_is_current']:
        data.setdefault('missing_data',[]).append({'code':'snapshot_inputs_changed','detail':'Saved snapshot is historical. Read company_sections/market.latest/search for current evidence.'})
    return tool_result('ok',data,sources=[{'id':prefix+ref,**source} for ref,source in snapshot['sources'].items()],returned=1)


class MorningBriefInput(BaseModel):
    symbols: list[str] | None = Field(default=None,max_length=8)
    sectors: list[str] | None = Field(default=None,max_length=8)
    limit: int = Field(default=8,ge=1,le=12)


def _morning_brief(db,_user,payload):
    from app.services.pipeline.briefing import read
    rows=read(db,symbols=payload.symbols,sectors=payload.sectors,limit=payload.limit)
    sources=[{k:r[k] for k in ('id','source_name','source_url','title','published_date')} for r in rows]
    data=[{k:v for k,v in row.items() if k not in ('source_name','source_url','title')}|{'source_ref':row['id']} for row in rows]
    return tool_result('ok' if rows else 'missing',{'extra_analysis':data,
        'qualification':'Analyst commentary, not verified financial or macro observations. Original news articles are retrieved independently.'},sources=sources,returned=len(rows))


def register_research_tools(registry: ToolRegistry) -> None:
    registry.register(ToolDefinition('research.morning_brief','1.0',
        'Dated extra sector/company interpretation from the public morning research feed. Optional issuer/sector filters. Numerical claims require separate original-source or SQL verification.',
        MorningBriefInput,'research:read',True,False,10,_morning_brief))
    registry.register(ToolDefinition('research.company_digest','1.0',
        'Saved compact company snapshot and cited AI thesis; dates, periods, reporting bases and missing data retained. Use company_sections/search for omitted older or detailed evidence. No portfolio or IPS.',
        CompanyDigestInput,'research:read',True,False,12,_company_digest))
    registry.register(ToolDefinition("research.event_relevance", "1.0",
        "Issuer-scoped direct events and three-factor AI-proposed indirect relationships with original evidence; no impact forecast",
        EventRelevanceInput, "research:read", True, False, 12, _event_relevance))
    registry.register(
        ToolDefinition(
            "research.search",
            "1.0",
            "Cited company, sector and broader economic/news passages with dates and pagination. Optional topics/date filters; set include_broader_context=false for company-only retrieval. Follow next_cursor for more stored evidence. Commentary is labelled, not a numerical fact source.",
            ResearchInput,
            "research:read",
            True,
            False,
            10,
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
            _company_sections,
        )
    )
    registry.register(
        ToolDefinition(
            "research.events",
            "1.0",
            "Stored events with citations and pagination: company symbol includes direct/stored indirect relevance; omit symbol for broader geopolitical/macro news and optional headline query",
            EventInput,
            "research:read",
            True,
            False,
            8,
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
            _instruments,
        )
    )


class EventRelevanceInput(BaseModel):
    symbol: str = Field(min_length=1, max_length=30)
    period_start: date | None = None
    period_end: date | None = None
    cursor: str | None = Field(default=None, pattern=r"^[0-9]+$")
    limit: int = Field(default=5, ge=1, le=20)

    @model_validator(mode="after")
    def validate_period(self):
        if self.period_start and self.period_end and self.period_end < self.period_start:
            raise ValueError("period_end must be on or after period_start")
        return self


def _event_relevance(db, user, payload):
    return _events(db, user, EventInput(entity_key=payload.symbol, period_start=payload.period_start,
        period_end=payload.period_end, cursor=payload.cursor, limit=payload.limit))
