"""Phase 7B consumer adapters for the shared Canonical Intelligence Context."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.intelligence_context import (
    ContextRefreshRequest,
    IntelligenceContextReceiptRecord,
)
from app.models.user import User
from app.models.workstation import Instrument
from app.schemas.intelligence_context import (
    ContextScope,
    ContextSectionName,
    IntelligenceContext,
    IntelligenceContextRequest,
    ResearchPurpose,
)
from app.services.context_builder import build_intelligence_context
from app.services.context_deficiency_bridge import ContextDeficiencyBridge


ASSISTANT_SECTION_MAP = {
    "security_fit": (
        ContextSectionName.PORTFOLIO,
        ContextSectionName.IPS,
        ContextSectionName.COMPANY_FACTS,
        ContextSectionName.MARKET_RISK,
        ContextSectionName.SECTOR,
        ContextSectionName.MACRO,
        ContextSectionName.EVENTS,
        ContextSectionName.RAG_EVIDENCE,
    ),
    "holding_evidence": (
        ContextSectionName.COMPANY_FACTS,
        ContextSectionName.EVENTS,
        ContextSectionName.RAG_EVIDENCE,
    ),
    "market_overview": (
        ContextSectionName.MARKET_RISK,
        ContextSectionName.SECTOR,
        ContextSectionName.MACRO,
        ContextSectionName.EVENTS,
    ),
}


@dataclass(frozen=True)
class ConsumedContext:
    context: IntelligenceContext
    receipt_record: IntelligenceContextReceiptRecord
    refresh_request: ContextRefreshRequest | None


def company_context_request(
    symbol: str,
    *,
    portfolio_id: str | None = None,
    research_purpose: ResearchPurpose | None = None,
    question: str | None = None,
) -> IntelligenceContextRequest:
    return IntelligenceContextRequest(
        symbol=symbol,
        scope=(
            ContextScope.PORTFOLIO_RELEVANCE if portfolio_id else ContextScope.COMPANY_INTELLIGENCE
        ),
        portfolio_id=portfolio_id,
        research_purpose=research_purpose,
        question=question,
    )


def assistant_context_request(
    symbol: str,
    *,
    intent: str,
    portfolio_id: str | None,
    question: str,
) -> IntelligenceContextRequest:
    if intent == "security_fit" and not portfolio_id:
        raise HTTPException(
            status_code=422,
            detail="Security Fit requires one selected portfolio and its confirmed IPS",
        )
    scope = (
        ContextScope.SECURITY_FIT if intent == "security_fit" else ContextScope.COMPANY_INTELLIGENCE
    )
    sections = ASSISTANT_SECTION_MAP.get(intent)
    return IntelligenceContextRequest(
        symbol=symbol,
        scope=scope,
        sections=sections,
        portfolio_id=portfolio_id if scope == ContextScope.SECURITY_FIT else None,
        question=question,
    )


def build_assistant_context(
    db: Session,
    user: User,
    instrument_id: str,
    *,
    intent: str,
    portfolio_id: str | None,
    question: str,
) -> tuple[IntelligenceContextRequest, IntelligenceContext]:
    instrument = db.get(Instrument, instrument_id)
    if instrument is None:
        raise HTTPException(status_code=404, detail="Instrument not found")
    request = assistant_context_request(
        instrument.symbol,
        intent=intent,
        portfolio_id=portfolio_id,
        question=question,
    )
    return request, build_intelligence_context(db, user, request)


def consume_context(
    db: Session,
    user: User,
    request: IntelligenceContextRequest,
    *,
    consumer_type: str,
    consumer_key: str,
    output_id: str | None = None,
    source_message_id: str | None = None,
    active: bool = True,
) -> ConsumedContext:
    context = build_intelligence_context(db, user, request)
    output_id = output_id or str(uuid4())
    visible, refresh = ContextDeficiencyBridge.production(
        db, user, publish=False
    ).record_and_schedule(
        db,
        user,
        request,
        context,
        active=active,
        consumer_type=consumer_type,
        consumer_key=consumer_key,
        source_message_id=source_message_id,
        output_id=output_id,
    )
    receipt = db.scalar(
        select(IntelligenceContextReceiptRecord).where(
            IntelligenceContextReceiptRecord.user_id == user.id,
            IntelligenceContextReceiptRecord.output_id == output_id,
        )
    )
    if receipt is None:  # pragma: no cover - persistence invariant
        raise RuntimeError("Canonical context receipt was not persisted")
    return ConsumedContext(visible, receipt, refresh)


def consume_company_research(
    db: Session,
    user: User,
    instrument_id: str,
    *,
    portfolio_id: str | None = None,
    research_purpose: ResearchPurpose | None = None,
    question: str | None = None,
    active: bool = True,
) -> ConsumedContext:
    instrument = db.get(Instrument, instrument_id)
    if instrument is None:
        raise HTTPException(status_code=404, detail="Instrument not found")
    request = company_context_request(
        instrument.symbol,
        portfolio_id=portfolio_id,
        research_purpose=research_purpose,
        question=question,
    )
    key = f"instrument:{instrument.id}:portfolio:{portfolio_id or 'none'}"
    return consume_context(
        db,
        user,
        request,
        consumer_type="company_research",
        consumer_key=key,
        active=active,
    )


def persist_built_assistant_context(
    db: Session,
    user: User,
    request: IntelligenceContextRequest,
    context: IntelligenceContext,
    *,
    conversation_id: str,
    message_id: str,
    output_id: str | None = None,
    active: bool = True,
) -> ConsumedContext:
    visible, refresh = ContextDeficiencyBridge.production(
        db, user, publish=False
    ).record_and_schedule(
        db,
        user,
        request,
        context,
        active=active,
        consumer_type="assistant",
        consumer_key=conversation_id,
        source_message_id=message_id,
        output_id=output_id or message_id,
    )
    receipt = db.scalar(
        select(IntelligenceContextReceiptRecord).where(
            IntelligenceContextReceiptRecord.user_id == user.id,
            IntelligenceContextReceiptRecord.output_id == (output_id or message_id),
        )
    )
    if receipt is None:  # pragma: no cover - persistence invariant
        raise RuntimeError("Assistant context receipt was not persisted")
    return ConsumedContext(visible, receipt, refresh)


def context_evidence(context: IntelligenceContext) -> list[dict[str, object]]:
    """Flatten the canonical evidence registry without manufacturing new IDs."""

    return [
        {
            **item.model_dump(mode="json"),
            "section": section.name.value,
        }
        for section in context.sections.values()
        for item in section.evidence
    ]


def context_citations(context: IntelligenceContext) -> list[dict[str, object]]:
    section = context.sections.get(ContextSectionName.RAG_EVIDENCE.value)
    if section is None or not isinstance(section.data, list):
        return []
    return [
        {
            **dict(chunk.get("citation") or {}),
            "symbol": chunk.get("symbol"),
            "relevance_score": chunk.get("score"),
        }
        for chunk in section.data
        if chunk.get("citation_eligible") is True and isinstance(chunk.get("citation"), dict)
    ]


def context_uncertainty(context: IntelligenceContext) -> list[str]:
    return list(
        dict.fromkeys(
            [
                *[item.reason for item in context.deficiencies],
                *[error for section in context.sections.values() for error in section.errors],
            ]
        )
    )


def company_research_response(consumed: ConsumedContext) -> dict[str, object]:
    """Compatibility view derived only from canonical sections during migration."""

    context = consumed.context
    facts_section = context.sections.get(ContextSectionName.COMPANY_FACTS.value)
    market_section = context.sections.get(ContextSectionName.MARKET_RISK.value)
    events_section = context.sections.get(ContextSectionName.EVENTS.value)
    rag_section = context.sections.get(ContextSectionName.RAG_EVIDENCE.value)
    portfolio_section = context.sections.get(ContextSectionName.PORTFOLIO.value)
    facts_data = (
        facts_section.data if facts_section and isinstance(facts_section.data, dict) else {}
    )
    market_data = (
        market_section.data if market_section and isinstance(market_section.data, dict) else {}
    )
    instrument = dict(facts_data.get("instrument") or {"symbol": context.symbol})
    raw_facts = (
        facts_data.get("fundamentals") if isinstance(facts_data.get("fundamentals"), list) else []
    )
    fundamentals = [
        {
            "taxonomy_key": row.get("metric"),
            "period_type": row.get("period_type"),
            "period_end": row.get("period_end"),
            "filing_date": row.get("filing_date"),
            "value": row.get("value"),
            "unit": row.get("unit"),
            "currency": row.get("currency"),
            "document_id": row.get("document_id"),
            "page_number": None,
            "classification": row.get("classification") or "filing_extracted",
            "source_url": row.get("source_url"),
            "provenance": {
                "source_name": next(
                    (
                        evidence.source.upper()
                        for evidence in (facts_section.evidence if facts_section else [])
                        if evidence.underlying_id.startswith(
                            (
                                f"financial_fact:{row.get('id')}",
                                f"standardized_fact:{row.get('id')}",
                            )
                        )
                    ),
                    None,
                ),
                "document_type": "structured_financials",
                "is_synthetic": False,
                "ingested_at": facts_section.as_of if facts_section else None,
            },
        }
        for row in raw_facts
    ]
    price = dict(market_data.get("price") or {}) if market_data else {}
    market = (
        None
        if not price
        else {
            "date": price.get("trade_date"),
            "close": price.get("close"),
            "volume": price.get("volume"),
            "change_percent": price.get("change_percent"),
            "quality_status": price.get("quality_status"),
            "adjustment_state": price.get("adjustment_state"),
            "source": market_section.evidence[0].source
            if market_section and market_section.evidence
            else None,
            "source_url": market_section.evidence[0].source_url
            if market_section and market_section.evidence
            else None,
        }
    )
    event_rows = (
        events_section.data if events_section and isinstance(events_section.data, list) else []
    )
    events = [
        {
            **row,
            "sources": [
                {
                    "source_name": source.get("source_name"),
                    "source_url": source.get("source_url"),
                    "published_at": source.get("published_at"),
                    "selection_status": "normalized",
                }
                for source in row.get("evidence", [])
            ],
        }
        for row in event_rows
    ]
    chunks = rag_section.data if rag_section and isinstance(rag_section.data, list) else []
    documents = [
        {
            "id": chunk.get("document_id"),
            "title": (chunk.get("citation") or {}).get("title"),
            "document_type": chunk.get("document_type"),
            "published_date": (chunk.get("citation") or {}).get("created_at"),
            "source_url": chunk.get("source_url"),
            "is_synthetic": False,
            "evidence_id": next(
                (
                    item.evidence_id
                    for item in (rag_section.evidence if rag_section else [])
                    if item.metadata.get("document_id") == chunk.get("document_id")
                ),
                None,
            ),
        }
        for chunk in chunks
    ]
    portfolio_relevance: list[dict[str, object]] = []
    if portfolio_section and isinstance(portfolio_section.data, dict):
        exposure = dict(portfolio_section.data.get("security_exposure") or {})
        portfolio_relevance.append(
            {
                "portfolio_id": portfolio_section.data.get("id"),
                "portfolio_name": portfolio_section.data.get("name"),
                "quantity": exposure.get("quantity", 0),
                "market_value": exposure.get("market_value", 0),
                "weight": exposure.get("weight", 0),
                "risk_context": {
                    "available": False,
                    "reason": "Use deterministic portfolio analysis for marginal risk calculations.",
                },
            }
        )
    return {
        "instrument": instrument,
        "market": market,
        "market_research": {
            "available": bool(market),
            "risk": market_data.get("risk_metrics"),
            "end_date": market_data.get("risk_calculation_as_of") or (market or {}).get("date"),
        },
        "fundamentals": fundamentals,
        "derived_fundamentals": {
            "latest": {},
            "growth": {},
            "ratios": {},
            "valuation": {
                "available": False,
                "reason": "Canonical valuation inputs were not requested by this context contract.",
            },
        },
        "documents": documents,
        "events": events,
        "intelligence_events": event_rows,
        "portfolio_relevance": portfolio_relevance,
        "has_synthetic_data": False,
        "excluded_synthetic_research": True,
        "context_contract_version": context.contract_version,
        "context": context.model_dump(mode="json"),
        "context_receipt": context.receipt.model_dump(mode="json"),
        "context_receipt_id": consumed.receipt_record.id,
        "refresh_request_id": consumed.refresh_request.id if consumed.refresh_request else None,
    }
