from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.rag import RagSearchRequest, RagSearchResponse
from app.services.rag_service import search_rag

router = APIRouter()


@router.post("/search", response_model=RagSearchResponse)
def rag_search(payload: RagSearchRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> RagSearchResponse:
    return search_rag(db, current_user, payload)
