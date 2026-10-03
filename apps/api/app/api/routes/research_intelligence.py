from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.research_intelligence import BatchRequest
from app.services.research_intelligence_service import (
    event_views,
    company_intelligence,
    portfolio_intelligence,
)
from app.services.research_job_service import preview_batch, enqueue_batch, job_status

router = APIRouter()


@router.get("/research/event-feed")
def event_feed(
    symbol: str | None = None,
    limit: int = Query(5, ge=1, le=20),
    window_days: int = Query(90, ge=1, le=365),
    cursor: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    rows = event_views(db, symbol=symbol, limit=limit + 1, offset=cursor, window_days=window_days)
    selected = rows[:limit]

    def raw_count(events):
        return sum(len(e.get("raw_event_ids", [e["raw_event_id"]])) for e in events)

    return {
        "events": selected,
        "next_cursor": cursor + raw_count(selected) if raw_count(rows) >= limit + 1 else None,
        "coverage": {"window_days": window_days, "source": "stored_selected_evidence"},
    }


@router.get("/research/companies/{symbol}/intelligence")
def company(symbol: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return company_intelligence(db, user, symbol)


@router.get("/portfolios/{portfolio_id}/event-intelligence")
def portfolio(
    portfolio_id: str,
    limit: int = Query(5, ge=1, le=20),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return portfolio_intelligence(db, user, portfolio_id, limit)


@router.post("/research/batches/preview")
def preview(
    payload: BatchRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    return preview_batch(db, user, payload)


@router.post("/research/batches", status_code=202)
def generate(
    payload: BatchRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    return enqueue_batch(db, user, payload)


@router.get("/research/jobs/{job_id}")
def status(job_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return job_status(db, user, job_id)
