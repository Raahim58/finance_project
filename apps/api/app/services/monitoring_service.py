import json
from datetime import UTC, datetime, timedelta
from hashlib import sha256

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.user import User
from app.models.workstation import Alert, Event, EventEntityLink, EventSource, IngestionRun, MonitoringRule, MonitoringRun, PortfolioIPSVersion, Recommendation
from app.services.audit_service import record_event
from app.services.market_service import get_market_freshness
from app.services.portfolio_service import get_portfolio_or_404, get_portfolio_summary
from app.services.workstation_service import ips_compliance, portfolio_quant
from app.services.canonical_market_service import latest_price

ALERT_STATUS_FILTERS = {"active", "acknowledged", "resolved", "all"}
RECOMMENDATION_DECISIONS = {"accepted", "reviewed", "dismissed", "rejected", "superseded", "resolved"}


def _rule(db: Session, user: User, rule_id: str) -> MonitoringRule:
    row = db.scalar(select(MonitoringRule).where(MonitoringRule.id == rule_id, MonitoringRule.user_id == user.id))
    if row is None: raise HTTPException(status_code=404, detail="Monitoring rule not found")
    return row


def list_rules(db: Session, user: User, portfolio_id: str | None = None):
    statement = select(MonitoringRule).where(MonitoringRule.user_id == user.id)
    if portfolio_id:
        get_portfolio_or_404(db, user, portfolio_id); statement = statement.where(MonitoringRule.portfolio_id == portfolio_id)
    return [{"id": row.id, "portfolio_id": row.portfolio_id, "rule_type": row.rule_type, "threshold": json.loads(row.threshold_json), "enabled": row.enabled, "deduplication_window_minutes": row.deduplication_window_minutes, "created_at": row.created_at} for row in db.scalars(statement.order_by(MonitoringRule.created_at.desc()))]


def update_rule(db: Session, user: User, rule_id: str, *, enabled: bool):
    row = _rule(db, user, rule_id); row.enabled = enabled; db.commit(); return {"id": row.id, "enabled": row.enabled}


def delete_rule(db: Session, user: User, rule_id: str):
    row = _rule(db, user, rule_id); db.delete(row); db.commit()


def _evaluate(db: Session, user: User, rule: MonitoringRule) -> tuple[bool, dict, str, str]:
    threshold = json.loads(rule.threshold_json)
    summary = get_portfolio_summary(db, user, rule.portfolio_id)
    if rule.rule_type in {"position_weight", "concentration"}:
        limit = float(threshold.get("maximum", threshold.get("max_weight", 0.25)))
        breaches = [{"symbol": item.symbol, "weight": float(item.market_value / summary.total_value)} for item in summary.holdings if summary.total_value and float(item.market_value / summary.total_value) > limit]
        return bool(breaches), {"limit": limit, "breaches": breaches, "as_of": str(summary.data_freshness_date)}, "concentration", f"{len(breaches)} position(s) exceed the configured {limit:.1%} weight limit."
    if rule.rule_type == "stale_data":
        freshness = get_market_freshness(db).model_dump(mode="json")
        return bool(freshness["is_stale"]), freshness, "stale_data", freshness.get("stale_warning") or "Market data is stale."
    if rule.rule_type in {"drawdown", "volatility", "var"}:
        quant = portfolio_quant(db, user, rule.portfolio_id)
        metrics = quant["portfolio"]
        key = {"drawdown": "max_drawdown", "volatility": "annual_volatility", "var": "historical_var_95"}[rule.rule_type]
        if metrics.get("available") is False:
            return False, {"reason": metrics.get("reason"), "run_id": quant.get("run_id")}, rule.rule_type, "Metric unavailable; no alert generated."
        actual = abs(float(metrics[key])); limit = float(threshold.get("maximum", 0))
        return actual > limit, {"metric": key, "actual": actual, "limit": limit, "run_id": quant.get("run_id"), "as_of": str(quant.get("data_cutoff"))}, rule.rule_type, f"{key} is {actual:.2%}, above the configured {limit:.2%} limit."
    if rule.rule_type == "liquidity":
        minimum_volume = float(threshold.get("minimum_daily_volume", 0))
        minimum_value = float(threshold.get("minimum_traded_value", 0))
        breaches = []
        for holding in summary.holdings:
            price = latest_price(db, holding.symbol)
            if price is None:
                breaches.append({"symbol": holding.symbol, "reason": "missing_canonical_price"})
            elif price.volume < minimum_volume or float(price.value) < minimum_value:
                breaches.append({"symbol": holding.symbol, "daily_volume": price.volume, "traded_value": float(price.value), "artifact_id": price.artifact_id, "as_of": price.trade_date})
        return bool(breaches), {"minimum_daily_volume": minimum_volume, "minimum_traded_value": minimum_value, "breaches": breaches}, "liquidity", f"{len(breaches)} holding(s) breached the configured liquidity floor."
    if rule.rule_type == "event":
        lookback_hours = int(threshold.get("lookback_hours", 24))
        symbols = [holding.symbol for holding in summary.holdings]
        statement = (
            select(Event, EventEntityLink)
            .join(EventEntityLink, EventEntityLink.event_id == Event.id)
            .where(EventEntityLink.entity_key.in_(symbols), Event.occurred_at >= datetime.now(UTC) - timedelta(hours=lookback_hours))
        )
        events = []
        for event, link in db.execute(statement):
            sources = list(db.scalars(select(EventSource).where(EventSource.event_id == event.id)))
            events.append({"event_id": event.id, "symbol": link.entity_key, "title": event.title, "event_type": event.event_type, "occurred_at": event.occurred_at, "materiality": event.materiality, "confidence": event.confidence, "sources": [{"name": source.source_name, "url": source.source_url, "document_id": source.document_id} for source in sources]})
        return bool(events), {"lookback_hours": lookback_hours, "events": events}, "event", f"{len(events)} sourced event(s) were linked to current holdings."
    if rule.rule_type == "ingestion_failure":
        lookback_hours = int(threshold.get("lookback_hours", 24))
        failures = list(db.scalars(select(IngestionRun).where(IngestionRun.status == "failed", IngestionRun.started_at >= datetime.now(UTC) - timedelta(hours=lookback_hours)).order_by(IngestionRun.started_at.desc())))
        evidence = {"lookback_hours": lookback_hours, "failures": [{"run_id": row.id, "provider": row.provider, "job_key": row.job_key, "error_class": row.error_class, "started_at": row.started_at} for row in failures]}
        return bool(failures), evidence, "ingestion_failure", f"{len(failures)} ingestion job(s) failed in the configured lookback."
    return False, {"reason": "Rule evaluator is awaiting the required structured feed"}, rule.rule_type, "No alert generated because required structured data is unavailable."


def _decision_context(db: Session, user: User, rule: MonitoringRule, evidence: dict) -> dict:
    portfolio = get_portfolio_or_404(db, user, rule.portfolio_id)
    version = db.get(PortfolioIPSVersion, portfolio.selected_ips_version_id) if portfolio.selected_ips_version_id else None
    constraints = json.loads(version.constraints_json) if version else {}
    related_ips_limit = constraints.get("max_instrument_weight") if rule.rule_type in {"position_weight", "concentration"} else constraints.get({"volatility": "target_volatility", "beta_shift": "target_beta"}.get(rule.rule_type, ""))
    threshold = json.loads(rule.threshold_json)
    current_value = None
    if evidence.get("breaches"):
        current_value = max((item.get("weight") for item in evidence["breaches"] if item.get("weight") is not None), default=None)
    elif evidence.get("actual") is not None:
        current_value = evidence["actual"]
    classification = "monitoring_warning"
    if related_ips_limit is not None and current_value is not None and float(current_value) > float(related_ips_limit):
        classification = "mandate_breach"
    return {
        **evidence,
        "rule_id": rule.id,
        "rule_type": rule.rule_type,
        "rule_threshold": threshold,
        "current_value": current_value,
        "related_ips_limit": related_ips_limit,
        "ips_version_id": version.id if version else None,
        "classification": classification,
        "rule_enabled": rule.enabled,
    }


def _resolve_inactive_alerts(db: Session, user: User, rule: MonitoringRule) -> None:
    for alert in db.scalars(select(Alert).where(Alert.user_id == user.id, Alert.portfolio_id == rule.portfolio_id, Alert.status == "open")):
        evidence = json.loads(alert.evidence_json)
        if evidence.get("rule_id") == rule.id:
            alert.status = "resolved"
            record_event(
                db, user, event_type="alert_resolved", entity_type="alert", entity_id=alert.id,
                portfolio_id=alert.portfolio_id, previous_state={"status": "open"}, new_state={"status": "resolved"},
                source="system_monitoring_run",
                note="Automatically resolved: the triggering rule condition no longer holds.",
            )


def run_monitoring(db: Session, user: User, portfolio_id: str):
    portfolio = get_portfolio_or_404(db, user, portfolio_id)
    run = MonitoringRun(portfolio_id=portfolio.id, status="running")
    db.add(run); db.flush()
    evaluations = []; created = []
    for rule in db.scalars(select(MonitoringRule).where(MonitoringRule.portfolio_id == portfolio.id, MonitoringRule.user_id == user.id, MonitoringRule.enabled.is_(True))):
        triggered, evidence, alert_type, message = _evaluate(db, user, rule)
        evidence = _decision_context(db, user, rule, evidence)
        evaluations.append({"rule_id": rule.id, "triggered": triggered, "evidence": evidence})
        if not triggered:
            _resolve_inactive_alerts(db, user, rule)
            continue
        window = datetime.now(UTC).timestamp() // (rule.deduplication_window_minutes * 60)
        key = sha256(f"{rule.id}:{alert_type}:{window}".encode()).hexdigest()
        existing = db.scalar(select(Alert).where(Alert.deduplication_key == key))
        if existing: continue
        alert = Alert(user_id=user.id, portfolio_id=portfolio.id, monitoring_run_id=run.id, deduplication_key=key, alert_type=alert_type, severity="warning", message=message, evidence_json=json.dumps(evidence, default=str))
        db.add(alert); db.flush(); created.append(alert.id)
        recommendation_trigger = f"monitor:{rule.id}:{key}"
        db.add(Recommendation(
            user_id=user.id, portfolio_id=portfolio.id, trigger=recommendation_trigger,
            evidence_json=json.dumps(evidence, default=str), ips_violation_json="[]",
            assumptions_json=json.dumps({"rule_type": rule.rule_type, "threshold": json.loads(rule.threshold_json)}),
            expected_effect_json=json.dumps({"available": False, "reason": "No trade or optimizer action is inferred automatically."}),
            uncertainty_json=json.dumps({"note": "Review source evidence and current freshness before acting."}),
            freshness_json=json.dumps({"market_as_of": str(summary_date(db, user, portfolio.id))}),
            message=f"Review this {alert_type} trigger and its evidence before changing the portfolio.", status="open",
        ))
    compliance = ips_compliance(db, user, portfolio.id)
    if compliance["violations"]:
        signature = sha256(json.dumps(compliance["violations"], sort_keys=True, default=str).encode()).hexdigest()
        existing = db.scalar(select(Recommendation).where(Recommendation.user_id == user.id, Recommendation.portfolio_id == portfolio.id, Recommendation.trigger == f"ips:{signature}", Recommendation.status == "open"))
        if existing is None:
            db.add(Recommendation(user_id=user.id, portfolio_id=portfolio.id, trigger=f"ips:{signature}", evidence_json=json.dumps(compliance, default=str), ips_violation_json=json.dumps(compliance["violations"], default=str), assumptions_json="{}", expected_effect_json="{}", uncertainty_json=json.dumps({"note": "No optimizer proposal is created automatically"}), freshness_json=json.dumps({"as_of": str(summary_date(db, user, portfolio.id))}), message="Review the recorded IPS violations before making portfolio changes.", status="open"))
    run.evidence_json = json.dumps(evaluations, default=str); run.status = "completed"; run.finished_at = datetime.now(UTC)
    db.commit(); db.refresh(run)
    return {"id": run.id, "portfolio_id": portfolio.id, "status": run.status, "evaluations": evaluations, "alerts_created": created, "finished_at": run.finished_at}


def summary_date(db: Session, user: User, portfolio_id: str):
    return get_portfolio_summary(db, user, portfolio_id).data_freshness_date


def list_alerts(db: Session, user: User, portfolio_id: str | None = None, status_filter: str = "active"):
    if status_filter not in ALERT_STATUS_FILTERS:
        raise HTTPException(status_code=422, detail=f"status must be one of {sorted(ALERT_STATUS_FILTERS)}")
    statement = select(Alert).where(Alert.user_id == user.id)
    if status_filter == "active":
        statement = statement.where(Alert.status == "open")
    elif status_filter != "all":
        statement = statement.where(Alert.status == status_filter)
    if portfolio_id: statement = statement.where(Alert.portfolio_id == portfolio_id)
    results = []
    for row in db.scalars(statement.order_by(Alert.created_at.desc())):
        evidence = json.loads(row.evidence_json)
        if not evidence.get("rule_id"):
            legacy_rule = db.scalar(select(MonitoringRule).where(MonitoringRule.user_id == user.id, MonitoringRule.portfolio_id == row.portfolio_id, MonitoringRule.rule_type.in_([row.alert_type, "position_weight" if row.alert_type == "concentration" else row.alert_type])))
            if legacy_rule:
                evidence = _decision_context(db, user, legacy_rule, evidence)
        results.append({"id": row.id, "portfolio_id": row.portfolio_id, "alert_type": row.alert_type, "severity": row.severity, "message": row.message, "evidence": evidence, "rule_id": evidence.get("rule_id"), "rule_type": evidence.get("rule_type", row.alert_type), "threshold": evidence.get("rule_threshold"), "current_value": evidence.get("current_value"), "related_ips_limit": evidence.get("related_ips_limit"), "classification": evidence.get("classification", "monitoring_warning"), "rule_enabled": evidence.get("rule_enabled"), "data_as_of": evidence.get("as_of"), "status": row.status, "acknowledged_at": row.acknowledged_at, "acknowledged_by_user_id": row.acknowledged_by_user_id, "acknowledgement_note": row.acknowledgement_note, "created_at": row.created_at})
    return results


def acknowledge_alert(db: Session, user: User, alert_id: str, note: str | None = None):
    row = db.scalar(select(Alert).where(Alert.id == alert_id, Alert.user_id == user.id))
    if row is None: raise HTTPException(status_code=404, detail="Alert not found")
    previous_status = row.status
    row.status = "acknowledged"; row.acknowledged_at = datetime.now(UTC); row.acknowledged_by_user_id = user.id; row.acknowledgement_note = note
    record_event(
        db, user, event_type="alert_acknowledged", entity_type="alert", entity_id=row.id, portfolio_id=row.portfolio_id,
        previous_state={"status": previous_status}, new_state={"status": row.status, "note": note}, note=note,
    )
    db.commit()
    return {"id": row.id, "status": row.status, "acknowledged_at": row.acknowledged_at, "acknowledged_by_user_id": row.acknowledged_by_user_id, "acknowledgement_note": row.acknowledgement_note}


def decide_recommendation(db: Session, user: User, recommendation_id: str, decision: str):
    if decision not in RECOMMENDATION_DECISIONS:
        raise HTTPException(status_code=422, detail=f"decision must be one of {sorted(RECOMMENDATION_DECISIONS)}")
    row = db.scalar(select(Recommendation).where(Recommendation.id == recommendation_id, Recommendation.user_id == user.id))
    if row is None:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    previous_status = row.status
    # Compatibility: legacy "accepted" meant the user reviewed the item. It did
    # not and still does not authorize a holding mutation or trade.
    row.status = "reviewed" if decision in {"accepted", "reviewed"} else decision
    record_event(
        db, user, event_type="recommendation_transition", entity_type="recommendation", entity_id=row.id, portfolio_id=row.portfolio_id,
        previous_state={"status": previous_status}, new_state={"status": row.status}, note=f"Decision: {decision}",
    )
    db.commit()
    return {"id": row.id, "status": row.status, "holdings_mutated": False}
