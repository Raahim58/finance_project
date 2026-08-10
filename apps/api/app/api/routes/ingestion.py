from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.services.ingestion_service import import_nccpl_csv, list_ingestion_runs, refresh_provider

router = APIRouter()


@router.get("/ingestion/runs")
def runs(limit: int = Query(default=100, ge=1, le=500), _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return list_ingestion_runs(db, limit)


@router.post("/ingestion/refresh")
def refresh(provider: str, run_key: str | None = None, _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = refresh_provider(db, provider, run_key)
    return {"id": row.id, "provider": row.provider, "status": row.status, "attempted_count": row.attempted_count, "accepted_count": row.accepted_count, "rejected_count": row.rejected_count, "finished_at": row.finished_at}


@router.post("/ingestion/nccpl/import")
async def nccpl_import(file: UploadFile = File(...), _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not (file.filename or "").lower().endswith(".csv"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Only CSV manual exports are accepted",
        )
    return import_nccpl_csv(db, await file.read())
