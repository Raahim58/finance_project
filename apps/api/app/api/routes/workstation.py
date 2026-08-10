from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.workstation import (
    IPSDraft,
    IPSVersionResponse,
    MonitoringRuleCreate,
    MonitoringRuleResponse,
    OptimizerRequest,
    OptimizerResponse,
    PortfolioQuantResponse,
    ProfileVersionResponse,
    RecommendationResponse,
    ScenarioRequest,
    ScenarioResponse,
    VersionDraft,
)
from app.services.workstation_service import (
    create_monitoring_rule,
    list_ips_versions,
    list_profile_versions,
    list_recommendations,
    portfolio_quant,
    run_optimizer,
    run_scenario,
    save_ips_version,
    save_profile_version,
)

router = APIRouter()


@router.post("/profiles/financial/draft", response_model=ProfileVersionResponse, status_code=201)
def profile_draft(payload: VersionDraft, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return save_profile_version(db, current_user, payload)


@router.post("/profiles/financial/confirm", response_model=ProfileVersionResponse, status_code=201)
def profile_confirm(payload: VersionDraft, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return save_profile_version(db, current_user, payload, confirm=True)


@router.get("/profiles/financial/versions", response_model=list[ProfileVersionResponse])
def profile_versions(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return list_profile_versions(db, current_user)


@router.post("/portfolios/{portfolio_id}/ips/draft", response_model=IPSVersionResponse, status_code=201)
def ips_draft(portfolio_id: str, payload: IPSDraft, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return save_ips_version(db, current_user, portfolio_id, payload)


@router.post("/portfolios/{portfolio_id}/ips/confirm", response_model=IPSVersionResponse, status_code=201)
def ips_confirm(portfolio_id: str, payload: IPSDraft, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return save_ips_version(db, current_user, portfolio_id, payload, confirm=True)


@router.get("/portfolios/{portfolio_id}/ips/versions", response_model=list[IPSVersionResponse])
def ips_versions(portfolio_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return list_ips_versions(db, current_user, portfolio_id)


@router.get("/portfolios/{portfolio_id}/quant", response_model=PortfolioQuantResponse)
def quant(portfolio_id: str, covariance_shrinkage: float = Query(default=0.20, ge=0, le=1), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return portfolio_quant(db, current_user, portfolio_id, covariance_shrinkage)


@router.post("/portfolios/{portfolio_id}/optimizer-runs", response_model=OptimizerResponse, status_code=201)
def optimizer(portfolio_id: str, payload: OptimizerRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return run_optimizer(db, current_user, portfolio_id, payload)


@router.post("/portfolios/{portfolio_id}/scenario-runs", response_model=ScenarioResponse, status_code=201)
def scenario(portfolio_id: str, payload: ScenarioRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return run_scenario(db, current_user, portfolio_id, payload)


@router.post("/portfolios/{portfolio_id}/monitoring/rules", response_model=MonitoringRuleResponse, status_code=status.HTTP_201_CREATED)
def monitoring_rule(portfolio_id: str, payload: MonitoringRuleCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return create_monitoring_rule(db, current_user, portfolio_id, payload.rule_type, payload.threshold)


@router.get("/recommendations", response_model=list[RecommendationResponse])
def recommendations(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return list_recommendations(db, current_user)
