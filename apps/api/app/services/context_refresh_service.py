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
from app.models.workstation import AssistantMessage
from app.schemas.intelligence_context import IntelligenceContext
from app.services.context_builder import build_intelligence_context
from app.services.context_deficiency_bridge import ContextDeficiencyBridge


@dataclass(frozen=True)
class ContextRefreshSweepResult:
    checked: int
    rebuilt: int
    marked_lazy: int
    still_running: int


def _assistant_refresh_summary(source: AssistantMessage, rebuilt: IntelligenceContext) -> str:
    previous = json.loads(source.evidence_json or "{}")
    old_receipt = previous.get("context_receipt") or {}
    old_states = old_receipt.get("section_states") or {}
    changed = [
        f"{name.replace('_', ' ')}: {old_states.get(name, 'unknown')} → {state.value}"
        for name, state in rebuilt.receipt.section_states.items()
        if old_states.get(name) != state.value
    ]
    detail = (
        "; ".join(changed[:6])
        if changed
        else "The underlying evidence or freshness timestamps changed without a section-state change."
    )
    return (
        "Context refresh update\n\n"
        f"Newly fetched data has been assembled using {rebuilt.contract_version}. {detail} "
        "Your original answer remains unchanged; this linked update records the refreshed evidence state."
    )


def reconcile_pending_contexts(
    db: Session,
    *,
    notify: Callable[[str, IntelligenceContext], None] | None = None,
    limit: int = 100,
    refresh_ids: list[str] | None = None,
) -> ContextRefreshSweepResult:
    """Poll linked durable ledgers and perform each refresh's single permitted rebuild."""

    statement = select(ContextRefreshRequest.id).where(
        ContextRefreshRequest.status.in_(("pending", "refreshing", "terminal")),
        ContextRefreshRequest.rebuild_count == 0,
    )
    if refresh_ids is not None:
        statement = statement.where(ContextRefreshRequest.id.in_(refresh_ids))
    ids = list(
        db.scalars(statement.order_by(ContextRefreshRequest.created_at).limit(limit))
    )
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
            receipt = bridge.persist_receipt(
                db,
                user,
                rebuilt,
                consumer_type=refresh.consumer_type,
                consumer_key=refresh.consumer_key,
            )
            db.flush()
            if refresh.consumer_type == "assistant" and refresh.source_message_id:
                source = db.get(AssistantMessage, refresh.source_message_id)
                if source is not None:
                    followup = AssistantMessage(
                        conversation_id=source.conversation_id,
                        role="assistant",
                        message_kind="context_refresh",
                        parent_message_id=source.id,
                        context_receipt_id=receipt.id,
                        content=_assistant_refresh_summary(source, rebuilt),
                        evidence_json=json.dumps(
                            {
                                "context_contract_version": rebuilt.contract_version,
                                "context_receipt": rebuilt.receipt.model_dump(mode="json"),
                                "refresh_request_id": refresh.id,
                                "original_message_id": source.id,
                            },
                            default=str,
                            sort_keys=True,
                        ),
                        tool_trace_json="[]",
                    )
                    db.add(followup)
                    db.flush()
                    receipt.output_id = followup.id
            notification = ContextRefreshNotification(
                refresh_request_id=refresh.id,
                receipt_id=receipt.id,
                user_id=user.id,
                context_id=rebuilt.context_id,
                status="pending",
                payload_json=json.dumps(
                    {
                        "context_id": rebuilt.context_id,
                        "content_hash": rebuilt.receipt.content_hash,
                        "status": rebuilt.status,
                        "message": rebuilt.message,
                    },
                    sort_keys=True,
                ),
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
