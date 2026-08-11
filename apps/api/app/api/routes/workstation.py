from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.workstation import (
    CapitalMarketAssumptionsResponse,
    CapmSmlResponse,
    EfficientFrontierResponse,
    IPSDraft,
    IPSComplianceResponse,
    IPSVersionResponse,
    MonitoringRuleCreate,
    MonitoringRuleResponse,
    OptimizerRequest,
    OptimizerResponse,
    PortfolioQuantResponse,
    PortfolioComparisonRequest,
    PortfolioComparisonResponse,
    ProfileVersionResponse,
    RecommendationResponse,
    RebalanceRequest,
    RebalanceResponse,
    ReturnDistributionResponse,
    RiskBudgetResponse,
    RollingRiskResponse,
    ScenarioRequest,
    ScenarioResponse,
    VersionDraft,
)
from app.services.decision_analytics_service import (
    capital_market_assumptions,
    capm_sml_analysis,
    compare_portfolio,
    efficient_frontier_analysis,
    return_distribution_analysis,
    risk_budget_analysis,
    rolling_risk_analysis,
)
from app.services.workstation_service import (
    create_monitoring_rule,
    ips_compliance,
    list_ips_versions,
    list_optimizer_runs,
    list_profile_versions,
    list_recommendations,
    list_scenario_runs,
    portfolio_quant,
    rebalance_preview,
    security_quant,
    efficient_frontier,
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


@router.get("/portfolios/{portfolio_id}/ips/compliance", response_model=IPSComplianceResponse)
def compliance(portfolio_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return ips_compliance(db, current_user, portfolio_id)


@router.get("/portfolios/{portfolio_id}/quant", response_model=PortfolioQuantResponse)
def quant(portfolio_id: str, covariance_shrinkage: float = Query(default=0.20, ge=0, le=1), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return portfolio_quant(db, current_user, portfolio_id, covariance_shrinkage)


@router.get("/quant/security/{instrument_id}")
def quant_security(instrument_id: str, db: Session = Depends(get_db)):
    return security_quant(db, instrument_id)


@router.get("/portfolios/{portfolio_id}/frontier", response_model=EfficientFrontierResponse)
def frontier(portfolio_id: str, points: int = Query(default=20, ge=5, le=100), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return efficient_frontier_analysis(db, current_user, portfolio_id, points)


@router.get("/portfolios/{portfolio_id}/assumptions", response_model=CapitalMarketAssumptionsResponse)
def assumptions(portfolio_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return capital_market_assumptions(db, current_user, portfolio_id)


@router.get("/portfolios/{portfolio_id}/capm-sml", response_model=CapmSmlResponse)
def capm_sml(portfolio_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return capm_sml_analysis(db, current_user, portfolio_id)


@router.get("/portfolios/{portfolio_id}/rolling-risk", response_model=RollingRiskResponse)
def rolling_risk(portfolio_id: str, window: int = Query(default=60, ge=20, le=252), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return rolling_risk_analysis(db, current_user, portfolio_id, window)


@router.get("/portfolios/{portfolio_id}/return-distribution", response_model=ReturnDistributionResponse)
def return_distribution(portfolio_id: str, bins: int = Query(default=18, ge=5, le=50), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return return_distribution_analysis(db, current_user, portfolio_id, bins)


@router.post("/portfolios/{portfolio_id}/comparison", response_model=PortfolioComparisonResponse)
def comparison(portfolio_id: str, payload: PortfolioComparisonRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return compare_portfolio(db, current_user, portfolio_id, payload)


@router.get("/portfolios/{portfolio_id}/risk-budget", response_model=RiskBudgetResponse)
def risk_budget(portfolio_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return risk_budget_analysis(db, current_user, portfolio_id)


@router.get("/portfolios/{portfolio_id}/risk", response_model=PortfolioQuantResponse)
def risk(portfolio_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return portfolio_quant(db, current_user, portfolio_id)


@router.get("/portfolios/{portfolio_id}/risk-contributions")
def contributions(portfolio_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    result = portfolio_quant(db, current_user, portfolio_id)
    return {"portfolio_id": portfolio_id, "data_cutoff": result["data_cutoff"], "risk_contributions": result["risk_contributions"], "run_id": result["run_id"]}


@router.post("/portfolios/{portfolio_id}/optimizer-runs", response_model=OptimizerResponse, status_code=201)
def optimizer(portfolio_id: str, payload: OptimizerRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return run_optimizer(db, current_user, portfolio_id, payload)


@router.get("/portfolios/{portfolio_id}/optimizer-runs")
def optimizer_history(portfolio_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return list_optimizer_runs(db, current_user, portfolio_id)


@router.post("/portfolios/{portfolio_id}/rebalance-preview", response_model=RebalanceResponse)
def rebalance(portfolio_id: str, payload: RebalanceRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return rebalance_preview(db, current_user, portfolio_id, payload)


@router.post("/portfolios/{portfolio_id}/scenario-runs", response_model=ScenarioResponse, status_code=201)
def scenario(portfolio_id: str, payload: ScenarioRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return run_scenario(db, current_user, portfolio_id, payload)


@router.get("/portfolios/{portfolio_id}/scenario-runs", response_model=list[ScenarioResponse])
def scenario_history(portfolio_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return list_scenario_runs(db, current_user, portfolio_id)


@router.post("/portfolios/{portfolio_id}/monitoring/rules", response_model=MonitoringRuleResponse, status_code=status.HTTP_201_CREATED)
def monitoring_rule(portfolio_id: str, payload: MonitoringRuleCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return create_monitoring_rule(db, current_user, portfolio_id, payload.rule_type, payload.threshold, payload.deduplication_window_minutes)


@router.get("/recommendations", response_model=list[RecommendationResponse])
def recommendations(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return list_recommendations(db, current_user)
