from datetime import date
import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.models.intelligence_context import ContextRefreshRequest, IntelligenceContextReceiptRecord
from app.models.workstation import DataSource
from app.schemas.event_intelligence import NormalizedEventResponse
from app.schemas.intelligence_context import IntelligenceContextRequest, ResearchPurpose
from app.schemas.research import (
    EventStudyRequest,
    HistoricalReplayRequest,
    InstrumentResponse,
    ScenarioDefinitionCreate,
    ScenarioDefinitionResponse,
)
from app.services.event_intelligence_service import list_normalized_events
from app.services.context_consumer_service import (
    ConsumedContext,
    company_research_response,
    consume_company_research,
)
from app.services.context_builder import build_intelligence_context
from app.services.context_deficiency_bridge import ContextDeficiencyBridge
from app.services.research_service import (
    instrument_detail,
    list_events,
    list_macro_series,
    macro_releases,
    market_series,
    run_event_study,
    search_instruments,
)
from app.services.scenario_service import (
    create_definition,
    historical_replay,
    list_definitions,
    list_scenario_templates,
)
from app.services.regime_service import macro_regime

router = APIRouter()


@router.get("/instruments", response_model=list[InstrumentResponse])
def instruments(
    query: str | None = None,
    instrument_type: str | None = None,
    sector: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    return search_instruments(db, query, instrument_type, sector, limit)


@router.get("/instruments/{instrument_id}")
def instrument(instrument_id: str, db: Session = Depends(get_db)):
    return instrument_detail(db, instrument_id)


@router.get("/market/series")
def series(
    instrument_id: str,
    start: date | None = None,
    end: date | None = None,
    db: Session = Depends(get_db),
):
    return market_series(db, instrument_id, start, end)


@router.get("/market/sources")
def market_sources(db: Session = Depends(get_db)):
    rows = db.scalars(
        select(DataSource)
        .where(DataSource.source_type == "market")
        .order_by(DataSource.priority.asc(), DataSource.name.asc())
    ).all()
    return [
        {
            "id": row.id,
            "name": row.name,
            "base_url": row.base_url,
            "priority": row.priority,
            "freshness_sla_minutes": row.freshness_sla_minutes,
            "enabled": row.enabled,
            "use_notes": row.use_notes,
        }
        for row in rows
    ]


@router.get("/macro/series")
def macro_series(db: Session = Depends(get_db)):
    return list_macro_series(db)


@router.get("/macro/releases")
def releases(series_id: str | None = None, db: Session = Depends(get_db)):
    return macro_releases(db, series_id)


@router.get("/macro/regime")
def regime(
    portfolio_id: str | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return macro_regime(db, current_user, portfolio_id)


@router.get("/companies/{instrument_id}/overview")
def overview(
    instrument_id: str,
    portfolio_id: str | None = None,
    research_purpose: ResearchPurpose | None = None,
    question: str | None = Query(default=None, min_length=1, max_length=2000),
    active: bool = True,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    consumed = consume_company_research(
        db,
        current_user,
        instrument_id,
        portfolio_id=portfolio_id,
        research_purpose=research_purpose,
        question=question,
        active=active,
    )
    return company_research_response(consumed)


@router.get("/research/context-refreshes/{refresh_id}")
def context_refresh(
    refresh_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    refresh = db.scalar(
        select(ContextRefreshRequest).where(
            ContextRefreshRequest.id == refresh_id,
            ContextRefreshRequest.user_id == current_user.id,
        )
    )
    if refresh is None:
        raise HTTPException(status_code=404, detail="Context refresh not found")
    request = IntelligenceContextRequest.model_validate(json.loads(refresh.request_json))
    if refresh.needs_rebuild:
        ContextDeficiencyBridge.production(db, current_user).rebuild_if_needed(
            db,
            refresh.id,
            rebuild=lambda value: build_intelligence_context(db, current_user, value),
        )
        db.refresh(refresh)
    if refresh.status != "rebuilt":
        return {
            "refresh_request_id": refresh.id,
            "status": refresh.status,
            "needs_rebuild": refresh.needs_rebuild,
        }
    context = build_intelligence_context(db, current_user, request)
    receipt = db.scalar(
        select(IntelligenceContextReceiptRecord)
        .where(
            IntelligenceContextReceiptRecord.user_id == current_user.id,
            IntelligenceContextReceiptRecord.context_id == context.context_id,
        )
        .order_by(IntelligenceContextReceiptRecord.created_at.desc())
        .limit(1)
    )
    if receipt is None:
        receipt = ContextDeficiencyBridge.persist_receipt(
            db,
            current_user,
            context,
            consumer_type=refresh.consumer_type,
            consumer_key=refresh.consumer_key,
        )
        db.commit()
    if refresh.consumer_type == "company_research":
        return {
            "refresh_request_id": refresh.id,
            "status": refresh.status,
            "result": company_research_response(ConsumedContext(context, receipt, refresh)),
        }
    return {
        "refresh_request_id": refresh.id,
        "status": refresh.status,
        "context_receipt": context.receipt.model_dump(mode="json"),
    }


@router.post("/research/context-refreshes/{refresh_id}/deactivate")
def deactivate_context_refresh(
    refresh_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    refresh = db.scalar(
        select(ContextRefreshRequest).where(
            ContextRefreshRequest.id == refresh_id,
            ContextRefreshRequest.user_id == current_user.id,
        )
    )
    if refresh is None:
        raise HTTPException(status_code=404, detail="Context refresh not found")
    if refresh.rebuild_count == 0:
        refresh.active = False
        db.commit()
    return {"refresh_request_id": refresh.id, "active": refresh.active}


@router.get("/companies/{instrument_id}/fundamentals")
def fundamentals(
    instrument_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return company_research_response(consume_company_research(db, current_user, instrument_id))[
        "fundamentals"
    ]


@router.get("/companies/{instrument_id}/documents")
def company_documents(
    instrument_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return company_research_response(consume_company_research(db, current_user, instrument_id))[
        "documents"
    ]


@router.get("/companies/{instrument_id}/events")
def company_events(
    instrument_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return company_research_response(consume_company_research(db, current_user, instrument_id))[
        "events"
    ]


@router.get(
    "/companies/{instrument_id}/intelligence-events", response_model=list[NormalizedEventResponse]
)
def company_intelligence_events(
    instrument_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return company_research_response(consume_company_research(db, current_user, instrument_id))[
        "intelligence_events"
    ]


@router.get("/companies/{instrument_id}/portfolio-relevance")
def relevance(
    instrument_id: str,
    portfolio_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return company_research_response(
        consume_company_research(db, current_user, instrument_id, portfolio_id=portfolio_id)
    )["portfolio_relevance"]


@router.get("/research/events")
def events(
    entity_key: str | None = None,
    event_type: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    return list_events(db, entity_key, event_type, limit)


@router.get("/research/intelligence-events", response_model=list[NormalizedEventResponse])
def intelligence_events(
    subject_type: str | None = None,
    subject_key: str | None = None,
    event_type: str | None = None,
    materiality: str | None = None,
    view: Literal[
        "material", "company_relevant", "portfolio_relevant", "all_classified", "unresolved", "all"
    ] = "material",
    include_unclassified: bool = False,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    return list_normalized_events(
        db,
        subject_type=subject_type,
        subject_key=subject_key,
        event_type=event_type,
        materiality=materiality,
        view=view,
        include_unclassified=include_unclassified,
        limit=limit,
    )


@router.post("/research/event-study")
def event_study(
    payload: EventStudyRequest, _: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    return run_event_study(db, payload)


@router.get("/portfolios/{portfolio_id}/scenarios", response_model=list[ScenarioDefinitionResponse])
def scenarios(
    portfolio_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    return list_definitions(db, current_user, portfolio_id)


@router.get("/scenario-templates")
def scenario_templates(_: User = Depends(get_current_user)):
    return list_scenario_templates()


@router.post(
    "/portfolios/{portfolio_id}/scenarios",
    response_model=ScenarioDefinitionResponse,
    status_code=201,
)
def create_scenario(
    portfolio_id: str,
    payload: ScenarioDefinitionCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return create_definition(db, current_user, portfolio_id, payload)


@router.post("/portfolios/{portfolio_id}/scenarios/historical-replay")
def replay(
    portfolio_id: str,
    payload: HistoricalReplayRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return historical_replay(db, current_user, portfolio_id, payload)
