from datetime import date

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.data_health import CompanyCompletenessResponse, DataHealthResponse
from app.services.data_health_service import company_completeness, source_health
from app.services.ingestion_service import (
    historical_gaps,
    import_nccpl_csv,
    list_ingestion_runs,
    refresh_provider,
    run_historical_backfill,
)

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
