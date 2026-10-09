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
from app.services.pipeline.event_reads import event_records
from app.domain.research_relevance import utc
from datetime import UTC, datetime

router = APIRouter()


@router.get("/research/event-feed")
def event_feed(
    symbol: str | None = None,
    limit: int = Query(5, ge=1, le=20),
    window_days: int = Query(90, ge=1, le=365),
    cursor: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    # Market browsing is chronological. The previous legacy-only path excluded
    # current classified records and placed every old high event before new medium ones.
    candidate_limit = min(1000, max(100, cursor + limit + 1))
    records = event_records(db, symbols=[symbol] if symbol else None,
        window_days=window_days, limit=candidate_limit, candidate_limit=candidate_limit)
    covered = {raw for row in records for raw in row.get("raw_event_ids", [])}
    legacy = event_views(db, symbol=symbol, limit=candidate_limit, window_days=window_days, newest_first=True)
    now = datetime.now(UTC)
    rows = [row for row in records + [row for row in legacy if row["raw_event_id"] not in covered]
            if utc(row["occurred_at"]) <= now]
    rows.sort(key=lambda row: (-utc(row["occurred_at"]).timestamp(), row["event_key"]))
    selected = rows[cursor:cursor + limit]

    return {
        "events": selected,
        "next_cursor": cursor + limit if len(rows) > cursor + limit else None,
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


@router.get("/research/companies/{symbol}/digest")
def digest(symbol: str, active: bool = True, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.services.research_intelligence_service import resolve_company
    from app.services.company_digest_service import read_digest
    return read_digest(db,user,resolve_company(db,symbol),active=active)


@router.post("/research/companies/{symbol}/digest/retry", status_code=202)
def retry_digest(symbol: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.services.research_intelligence_service import resolve_company
    from app.services.company_digest_service import read_digest
    return read_digest(db,user,resolve_company(db,symbol),active=True,retry=True)
