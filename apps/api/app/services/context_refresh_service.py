"""Automatic terminal-state reconciliation for durable context refresh requests."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.intelligence_context import ContextRefreshNotification, ContextRefreshRequest
from app.models.user import User
from app.schemas.intelligence_context import IntelligenceContext
from app.services.context_builder import build_intelligence_context
from app.services.context_deficiency_bridge import ContextDeficiencyBridge


@dataclass(frozen=True)
class ContextRefreshSweepResult:
    checked: int
    rebuilt: int
    marked_lazy: int
    still_running: int


def reconcile_pending_contexts(
    db: Session,
    *,
    notify: Callable[[str, IntelligenceContext], None] | None = None,
    limit: int = 100,
) -> ContextRefreshSweepResult:
    """Poll linked durable ledgers and perform each refresh's single permitted rebuild."""

    ids = list(db.scalars(select(ContextRefreshRequest.id).where(
        ContextRefreshRequest.status.in_(("pending", "refreshing", "terminal")),
        ContextRefreshRequest.rebuild_count == 0,
    ).order_by(ContextRefreshRequest.created_at).limit(limit)))
    rebuilt_count = lazy = running = 0
    for refresh_id in ids:
        refresh = db.get(ContextRefreshRequest, refresh_id)
        if refresh is None:
            continue
        user = db.get(User, refresh.user_id)
        if user is None:
            refresh.status = "failed"
            db.commit()
            continue
        bridge = ContextDeficiencyBridge.production(db, user)
        rebuilt = bridge.reconcile(
            db,
            refresh.id,
            rebuild=lambda request, current_user=user: build_intelligence_context(
                db, current_user, request
            ),
            notify=None,
        )
        db.expire_all()
        refresh = db.get(ContextRefreshRequest, refresh_id)
        if rebuilt is not None:
            receipt = bridge.persist_receipt(db, user, rebuilt)
            db.flush()
            notification = ContextRefreshNotification(
                refresh_request_id=refresh.id,
                receipt_id=receipt.id,
                user_id=user.id,
                context_id=rebuilt.context_id,
                status="pending",
                payload_json=json.dumps({
                    "context_id": rebuilt.context_id,
                    "content_hash": rebuilt.receipt.content_hash,
                    "status": rebuilt.status,
                    "message": rebuilt.message,
                }, sort_keys=True),
                delivered_at=None,
            )
            db.add(notification)
            db.commit()
            if notify:
                try:
                    notify(user.id, rebuilt)
                except Exception:
                    # The durable pending outbox remains available for retry/delivery.
                    pass
                else:
                    notification.status = "delivered"
                    notification.delivered_at = datetime.now(UTC)
                    refresh.notified_at = notification.delivered_at
                    db.commit()
            rebuilt_count += 1
        elif refresh and refresh.needs_rebuild:
            lazy += 1
        else:
            running += 1
    return ContextRefreshSweepResult(len(ids), rebuilt_count, lazy, running)
