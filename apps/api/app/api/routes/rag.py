from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.rag import RagSearchRequest, RagSearchResponse
from app.services.rag_service import search_rag

router = APIRouter()


@router.post("/search", response_model=RagSearchResponse)
def rag_search(payload: RagSearchRequest, db: Session = Depends(get_db)) -> RagSearchResponse:
    return search_rag(db, payload)
