from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.models.evidence import EvidenceRefreshRequest
from app.models.workstation import Instrument
from app.schemas.evidence import (
    EvidenceHistoricalCreate,
    EvidenceRefreshCreate,
    EvidenceRefreshResponse,
)
from app.schemas.data_health import CompanyCompletenessResponse, DataHealthResponse
from app.services.data_health_service import company_completeness, source_health
from app.services.ingestion_service import (
    historical_gaps,
    import_nccpl_csv,
    list_ingestion_runs,
    refresh_provider,
    run_historical_backfill,
)
from app.ingestion.evidence_catalog import SECTOR_DRIVERS, TOPIC_QUERIES
from app.jobs.evidence_tasks import historical_hydrate, targeted_refresh
from app.services.evidence_scheduler_service import evidence_operational_status
from app.services.evidence_history_service import create_historical_request

router = APIRouter()


@router.get("/ingestion/health", response_model=DataHealthResponse)
def health(_: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return source_health(db)


@router.get("/ingestion/companies/{symbol}/completeness", response_model=CompanyCompletenessResponse)
def completeness(symbol: str, _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return company_completeness(db, symbol)


@router.get("/ingestion/runs")
def runs(limit: int = Query(default=100, ge=1, le=500), _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return list_ingestion_runs(db, limit)


@router.post("/ingestion/refresh")
def refresh(provider: str, run_key: str | None = None, _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = refresh_provider(db, provider, run_key)
    return {"id": row.id, "provider": row.provider, "status": row.status, "attempted_count": row.attempted_count, "accepted_count": row.accepted_count, "updated_count": row.updated_count, "rejected_count": row.rejected_count, "latest_observation_at": row.latest_observation_at, "error": row.error_message, "finished_at": row.finished_at}


@router.post("/ingestion/market-history")
def market_history(
    symbols: list[str] = Query(...),
    start: date = Query(...),
    end: date = Query(default_factory=date.today),
    provider: str = Query(default="dps"),
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = run_historical_backfill(db, provider_name=provider, symbols=symbols, start=start, end=end)
    return {"id": row.id, "status": row.status, "attempted_count": row.attempted_count, "accepted_count": row.accepted_count, "rejected_count": row.rejected_count, "error": row.error_message}


@router.get("/ingestion/market-history/gaps")
def market_history_gaps(
    symbol: str,
    start: date,
    end: date,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return historical_gaps(db, symbol, start, end)


@router.post("/ingestion/nccpl/import")
async def nccpl_import(file: UploadFile = File(...), _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not (file.filename or "").lower().endswith(".csv"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Only CSV manual exports are accepted",
        )
    return import_nccpl_csv(db, await file.read())


def _serialize_evidence_request(row: EvidenceRefreshRequest) -> EvidenceRefreshResponse:
    return EvidenceRefreshResponse.model_validate(row, from_attributes=True)


def _target_query(db: Session, payload: EvidenceRefreshCreate) -> tuple[str, str]:
    if payload.scope_type == "symbol":
        instrument = db.scalar(
            select(Instrument).where(Instrument.symbol == payload.value.strip().upper())
        )
        if instrument is None:
            raise HTTPException(status_code=404, detail="Instrument not found")
        return f"symbol:{instrument.symbol}", f'(\"{instrument.symbol}\" OR \"{instrument.name}\") AND Pakistan'
    if payload.scope_type == "topic":
        key = payload.value.strip().lower().replace(" ", "_")
        query = TOPIC_QUERIES.get(key)
        if query is None:
            raise HTTPException(status_code=422, detail="Unknown configured evidence topic")
        return f"topic:{key}", query
    if payload.scope_type == "sector":
        key = payload.value.strip().lower()
        drivers = SECTOR_DRIVERS.get(key)
        if not drivers:
            raise HTTPException(status_code=422, detail="Unknown configured PSX sector")
        terms = " OR ".join(f'\"{term}\"' for term in drivers[:10])
        return f"sector:{key}", f"Pakistan AND ({terms})"
    return "query:custom", payload.value


@router.post(
    "/ingestion/evidence/refresh",
    response_model=EvidenceRefreshResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def request_evidence_refresh(
    payload: EvidenceRefreshCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    scope_key, query = _target_query(db, payload)
    row = EvidenceRefreshRequest(
        requested_by_user_id=current_user.id,
        request_type="targeted",
        scope_key=scope_key,
        query_text=query,
        source_keys_json='["gdelt"]',
        status="queued",
        priority_class="live",
        max_candidates=payload.max_candidates,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    row.status = "running"
    row.started_at = datetime.now(UTC)
    db.commit()
    try:
        targeted_refresh.apply_async(args=(row.id,), queue="evidence_discovery", priority=0)
    except Exception as exc:
        row.status = "queued"
        row.error_class = type(exc).__name__
        row.error_message = str(exc)[:2000]
        db.commit()
    db.refresh(row)
    return _serialize_evidence_request(row)


@router.post(
    "/ingestion/evidence/historical",
    response_model=EvidenceRefreshResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def request_evidence_history(
    payload: EvidenceHistoricalCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    instrument = None
    if payload.symbol:
        instrument = db.scalar(select(Instrument).where(Instrument.symbol == payload.symbol))
        if instrument is None:
            raise HTTPException(status_code=404, detail="Instrument not found")
    try:
        row = create_historical_request(
            db,
            preset_key=payload.preset,
            instrument=instrument,
            requested_by_user_id=current_user.id,
            date_from=payload.date_from,
            date_to=payload.date_to,
            source_keys=tuple(payload.source_keys) if payload.source_keys else None,
            max_candidates=payload.max_candidates,
            fetch_budget=payload.fetch_budget,
            storage_budget_bytes=(
                payload.storage_budget_mb * 1024 * 1024
                if payload.storage_budget_mb
                else None
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    row.status = "running"
    row.started_at = datetime.now(UTC)
    db.commit()
    try:
        historical_hydrate.apply_async(args=(row.id,), queue="historical_hydrate", priority=8)
    except Exception as exc:
        row.status = "queued"
        row.error_class = type(exc).__name__
        row.error_message = str(exc)[:2000]
        db.commit()
    db.refresh(row)
    return _serialize_evidence_request(row)


@router.get("/ingestion/evidence/requests", response_model=list[EvidenceRefreshResponse])
def evidence_requests(
    limit: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = db.scalars(
        select(EvidenceRefreshRequest)
        .where(EvidenceRefreshRequest.requested_by_user_id == current_user.id)
        .order_by(EvidenceRefreshRequest.created_at.desc())
        .limit(limit)
    ).all()
    return [_serialize_evidence_request(row) for row in rows]


@router.get("/ingestion/evidence/operations")
def evidence_operations(_: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return evidence_operational_status(db)
