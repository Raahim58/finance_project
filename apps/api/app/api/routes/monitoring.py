from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.models.workstation import Recommendation
from app.services.monitoring_service import acknowledge_alert, delete_rule, list_alerts, list_rules, run_monitoring, update_rule

router = APIRouter()


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
def alerts(portfolio_id: str | None = None, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return list_alerts(db, current_user, portfolio_id)


@router.post("/monitoring/alerts/{alert_id}/acknowledge")
def acknowledge(alert_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return acknowledge_alert(db, current_user, alert_id)


@router.patch("/recommendations/{recommendation_id}")
def decide_recommendation(recommendation_id: str, decision: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if decision not in {"accepted", "dismissed"}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="decision must be accepted or dismissed",
        )
    row = db.scalar(select(Recommendation).where(Recommendation.id == recommendation_id, Recommendation.user_id == current_user.id))
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recommendation not found")
    row.status = decision; db.commit(); return {"id": row.id, "status": row.status}
