
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.models.evidence import EvidenceRefreshRequest
from app.models.workstation import Instrument
from app.schemas.evidence import (
    EvidenceRefreshCreate,
    EvidenceRefreshResponse,
)
from app.schemas.data_health import CompanyCompletenessResponse, DataHealthResponse
from app.services.data_health_service import company_completeness, source_health
from app.services.ingestion_service import (
    list_ingestion_runs,
)
from app.ingestion.evidence_catalog import SECTOR_DRIVERS, TOPIC_QUERIES

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


