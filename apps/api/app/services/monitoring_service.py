import json
from datetime import UTC, datetime, timedelta
from hashlib import sha256

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.user import User
from app.models.workstation import Alert, Event, EventEntityLink, EventSource, IngestionRun, MonitoringRule, MonitoringRun, Recommendation
from app.services.market_service import get_market_freshness
from app.services.portfolio_service import get_portfolio_or_404, get_portfolio_summary
from app.services.workstation_service import ips_compliance, portfolio_quant
from app.services.canonical_market_service import latest_price


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


def run_monitoring(db: Session, user: User, portfolio_id: str):
    portfolio = get_portfolio_or_404(db, user, portfolio_id)
    run = MonitoringRun(portfolio_id=portfolio.id, status="running")
    db.add(run); db.flush()
    evaluations = []; created = []
    for rule in db.scalars(select(MonitoringRule).where(MonitoringRule.portfolio_id == portfolio.id, MonitoringRule.user_id == user.id, MonitoringRule.enabled.is_(True))):
        triggered, evidence, alert_type, message = _evaluate(db, user, rule)
        evaluations.append({"rule_id": rule.id, "triggered": triggered, "evidence": evidence})
        if not triggered: continue
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


def list_alerts(db: Session, user: User, portfolio_id: str | None = None):
    statement = select(Alert).where(Alert.user_id == user.id)
    if portfolio_id: statement = statement.where(Alert.portfolio_id == portfolio_id)
    return [{"id": row.id, "portfolio_id": row.portfolio_id, "alert_type": row.alert_type, "severity": row.severity, "message": row.message, "evidence": json.loads(row.evidence_json), "status": row.status, "acknowledged_at": row.acknowledged_at, "created_at": row.created_at} for row in db.scalars(statement.order_by(Alert.created_at.desc()))]


def acknowledge_alert(db: Session, user: User, alert_id: str):
    row = db.scalar(select(Alert).where(Alert.id == alert_id, Alert.user_id == user.id))
    if row is None: raise HTTPException(status_code=404, detail="Alert not found")
    row.status = "acknowledged"; row.acknowledged_at = datetime.now(UTC); db.commit()
    return {"id": row.id, "status": row.status, "acknowledged_at": row.acknowledged_at}
