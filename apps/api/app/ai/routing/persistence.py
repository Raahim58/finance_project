"""Best-effort durable routing log. A logging failure must never fail a question."""
from __future__ import annotations

import json
import logging

from app.db.session import SessionLocal
from app.models.routing import RouteBudgetLog, RouteDecisionRecord

log = logging.getLogger(__name__)


def record_routing(user_id: str, execution_id: str, record: dict) -> bool:
    """Persist one decision (idempotent per execution). `record` is RoutedPlan.to_record()."""
    try:
        decision, budget = record['decision'], record.get('budget')
        with SessionLocal.begin() as db:
            if db.query(RouteDecisionRecord.id).filter_by(execution_id=execution_id).first():
                return False
            row = RouteDecisionRecord(
                user_id=user_id, execution_id=execution_id, primary_route=decision['primary'],
                secondary_routes_json=json.dumps(decision['secondary']),
                decision_source=decision['decision_source'], confidence=decision['confidence'],
                fallback_used=decision['fallback_used'], flags_json=json.dumps(decision['flags']),
                scores_json=json.dumps(decision['scores']), blocks_json=json.dumps(record['blocks']),
                missing_blocks_json=json.dumps(record['missing_blocks']),
                router_version=decision['router_version'], planner_version=record['planner_version'])
            db.add(row)
            db.flush()
            if budget:
                db.add(RouteBudgetLog(
                    route_decision_id=row.id, cap=budget['cap'], pre_steps=budget['pre_steps'],
                    post_steps=budget['post_steps'], dropped_json=json.dumps(budget['dropped']),
                    missing_required_json=json.dumps(budget['missing_required'])))
        return True
    except Exception:
        log.warning('routing log persistence failed', exc_info=True)
        return False
