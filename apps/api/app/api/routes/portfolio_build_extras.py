from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.services.portfolio_build_extras import build_extras

router = APIRouter()


class BuildExtrasRequest(BaseModel):
    target_weights: dict[str, float] | None = None


@router.post("/portfolios/{portfolio_id}/build-extras")
def post_build_extras(portfolio_id: str, payload: BuildExtrasRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return build_extras(db, user, portfolio_id, payload.target_weights)
