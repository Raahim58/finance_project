from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.services.portfolio_scenarios_extras import scenario_run_extras

router = APIRouter()


class ScenarioRunExtra(BaseModel):
    id: str
    created_at: datetime
    scenario_type: str | None = None
    shocks: dict[str, dict[str, float]]
    volatility_before: float | None = None
    volatility_after: float | None = None
    volatility_change: float | None = None
    volatility_unavailable_reason: str | None = None


class ScenarioRunExtrasResponse(BaseModel):
    portfolio_id: str
    volatility_method: str
    runs: list[ScenarioRunExtra]


@router.get("/portfolios/{portfolio_id}/scenario-run-extras", response_model=ScenarioRunExtrasResponse)
def scenario_extras(portfolio_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return scenario_run_extras(db, current_user, portfolio_id)
