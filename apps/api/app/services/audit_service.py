import json
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.user import User
from app.models.workstation import AuditEvent


def record_event(
    db: Session,
    user: User,
    *,
    event_type: str,
    entity_type: str,
    entity_id: str,
    portfolio_id: str | None = None,
    entity_version: int | None = None,
    previous_state: dict | None = None,
    new_state: dict | None = None,
    data_cutoff: date | None = None,
    source: str | None = None,
    note: str | None = None,
) -> AuditEvent:
    """Add an immutable audit row to the session without committing.

    Callers add this alongside the primary mutation and let the existing
    `db.commit()` for that mutation persist both atomically.
    """
    row = AuditEvent(
        user_id=user.id,
        portfolio_id=portfolio_id,
        event_type=event_type,
        entity_type=entity_type,
        entity_id=entity_id,
        entity_version=entity_version,
        previous_state_json=json.dumps(previous_state if previous_state is not None else {}, default=str),
        new_state_json=json.dumps(new_state if new_state is not None else {}, default=str),
        data_cutoff=data_cutoff,
        source=source,
        note=note,
    )
    db.add(row)
    return row


def serialize_event(row: AuditEvent) -> dict:
    return {
        "id": row.id,
        "user_id": row.user_id,
        "portfolio_id": row.portfolio_id,
        "event_type": row.event_type,
        "entity_type": row.entity_type,
        "entity_id": row.entity_id,
        "entity_version": row.entity_version,
        "previous_state": json.loads(row.previous_state_json),
        "new_state": json.loads(row.new_state_json),
        "data_cutoff": row.data_cutoff,
        "source": row.source,
        "note": row.note,
        "created_at": row.created_at,
    }


def list_audit_events(db: Session, user: User, portfolio_id: str | None = None, limit: int = 200) -> list[dict]:
    statement = select(AuditEvent).where(AuditEvent.user_id == user.id)
    if portfolio_id:
        statement = statement.where(AuditEvent.portfolio_id == portfolio_id)
    rows = db.scalars(statement.order_by(AuditEvent.created_at.desc()).limit(limit))
    return [serialize_event(row) for row in rows]
