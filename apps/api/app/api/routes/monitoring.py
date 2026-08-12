from pydantic import BaseModel
from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.services.audit_service import list_audit_events
from app.services.monitoring_service import acknowledge_alert, decide_recommendation, delete_rule, list_alerts, list_rules, run_monitoring, update_rule

router = APIRouter()


class AlertAcknowledgeRequest(BaseModel):
    note: str | None = None


@router.get("/monitoring/rules")
def rules(portfolio_id: str | None = None, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return list_rules(db, current_user, portfolio_id)


@router.patch("/monitoring/rules/{rule_id}")
def patch_rule(rule_id: str, enabled: bool, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return update_rule(db, current_user, rule_id, enabled=enabled)


@router.delete("/monitoring/rules/{rule_id}", status_code=204)
def remove_rule(rule_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    delete_rule(db, current_user, rule_id); return Response(status_code=204)


@router.post("/monitoring/runs/{portfolio_id}", status_code=201)
def monitor(portfolio_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return run_monitoring(db, current_user, portfolio_id)


@router.get("/monitoring/alerts")
def alerts(portfolio_id: str | None = None, status: str = "active", current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return list_alerts(db, current_user, portfolio_id, status)


@router.post("/monitoring/alerts/{alert_id}/acknowledge")
def acknowledge(alert_id: str, payload: AlertAcknowledgeRequest = AlertAcknowledgeRequest(), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return acknowledge_alert(db, current_user, alert_id, payload.note)


@router.patch("/recommendations/{recommendation_id}")
def patch_recommendation(recommendation_id: str, decision: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return decide_recommendation(db, current_user, recommendation_id, decision)


@router.get("/audit-events")
def audit_events(portfolio_id: str | None = None, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return list_audit_events(db, current_user, portfolio_id)
