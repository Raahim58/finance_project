from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.models.user import User
from app.schemas.intelligence import CandidateEvaluationRequest, SaveCandidateProposalRequest
from app.services.intelligence_service import evaluate_candidate, save_candidate_proposal, security_intelligence


router = APIRouter()


@router.get("/intelligence/securities/{symbol}")
def context(symbol: str, portfolio_id: str | None = Query(default=None), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return security_intelligence(db, current_user, symbol, portfolio_id)


@router.post("/intelligence/securities/{symbol}/evaluate")
def evaluate(symbol: str, payload: CandidateEvaluationRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return evaluate_candidate(db, current_user, symbol, payload)


@router.post("/intelligence/securities/{symbol}/proposals", status_code=201)
def save(symbol: str, payload: SaveCandidateProposalRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return save_candidate_proposal(db, current_user, symbol, payload)
