"""Ownership-checked workspace reads, SSE replay, cancellation and summary actions."""
import base64
import json
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, select, func, tuple_
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from app.db.session import Base
from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.models.workstation import Conversation, AssistantMessage
from app.models.assistant_execution import AssistantExecution
from app.services import assistant_execution, assistant_events, assistant_memory
from app.core.security import decrypt_secret, encrypt_secret
from app.models.assistant_workspace import ConversationSummary
from app.services.assistant_policy import selected_policy

router = APIRouter()


def cursor_encode(date, identifier):
    return base64.urlsafe_b64encode(json.dumps([date.isoformat(), identifier]).encode()).decode()


def cursor_decode(value):
    try:
        date, identifier = json.loads(base64.urlsafe_b64decode(value))
        return datetime.fromisoformat(date), identifier
    except (ValueError, TypeError, json.JSONDecodeError):
        raise HTTPException(422, "Invalid pagination cursor")


@router.get("/assistant/workspace/conversations")
def conversations(cursor: str | None = None, limit: int = Query(30, ge=1, le=100),
                  user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    activity = func.coalesce(select(func.max(AssistantMessage.created_at)).where(AssistantMessage.conversation_id == Conversation.id).scalar_subquery(), Conversation.created_at).label("activity")
    statement = select(Conversation, activity).where(Conversation.user_id == user.id)
    if cursor:
        statement = statement.where(tuple_(activity, Conversation.id) < cursor_decode(cursor))
    rows = list(db.execute(statement.order_by(activity.desc(), Conversation.id.desc()).limit(limit + 1)))
    result = []
    for row, latest in rows[:limit]:
        active = db.scalar(select(AssistantExecution).where(AssistantExecution.conversation_id == row.id,
                           AssistantExecution.status.in_(["queued", "running"])))
        result.append({"id": row.id, "title": row.title, "latest_activity": latest,
                       "active_run": {"execution_id": active.id, "status": active.status} if active else None,
                       "summary_failure": row.summary_failure})
    return {"items": result, "next_cursor": cursor_encode(rows[limit-1][1], rows[limit-1][0].id) if len(rows) > limit else None}


@router.get("/assistant/workspace/conversations/{identifier}/messages")
def messages(identifier: str, cursor: str | None = None, limit: int = Query(40, ge=1, le=100),
             user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    conversation = assistant_memory.owned_conversation(db, user.id, identifier)
    statement = select(AssistantMessage).where(AssistantMessage.conversation_id == identifier)
    if cursor:
        statement = statement.where(tuple_(AssistantMessage.created_at, AssistantMessage.id) < cursor_decode(cursor))
    rows = list(db.scalars(statement.order_by(AssistantMessage.created_at.desc(), AssistantMessage.id.desc()).limit(limit+1)))
    items = [{"id": r.id, "role": r.role, "content": r.content, "context": json.loads(r.context_json),
              "execution_id": r.execution_id, "outcome": r.outcome, "evidence": json.loads(r.evidence_json),
              "created_at": r.created_at} for r in reversed(rows[:limit])]
    active = db.scalar(select(AssistantExecution).where(AssistantExecution.conversation_id == identifier,
                       AssistantExecution.status.in_(["queued", "running"])))
    # Terminal partial/error runs remain inspectable after refresh even without final messages.
    executions = list(db.scalars(select(AssistantExecution).where(AssistantExecution.conversation_id == identifier)
                                 .order_by(AssistantExecution.created_at.desc()).limit(limit)))
    summary = assistant_memory.latest_summary(db, identifier)
    return {"items": items, "next_cursor": cursor_encode(rows[limit-1].created_at, rows[limit-1].id) if len(rows)>limit else None,
            "active_run": {"execution_id": active.id, "status": active.status} if active else None,
            "runs": [{"execution_id": r.id, "status": r.status, "error_code": r.error_code} for r in executions],
            "summary_failure": conversation.summary_failure,
            "summary": {"version": summary.version, "text": decrypt_secret(summary.content_encrypted), "covered_through_message_id": summary.covered_through_message_id} if summary else None}


@router.get("/assistant/runs/{identifier}/events")
async def events(identifier: str, after: int = Query(0, ge=0), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    assistant_execution.owned(db, user.id, identifier)
    # The subscription uses its own short-lived sessions. Do not retain an
    # ownership-check transaction/pool connection for the lifetime of SSE.
    db.close()
    return StreamingResponse(assistant_events.subscribe(identifier, after), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/assistant/runs/{identifier}/cancel")
async def cancel(identifier: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return {"status": assistant_execution.cancel(db, user.id, identifier)}


@router.post("/assistant/workspace/conversations/{identifier}/retry-summary")
def retry_summary(identifier: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    conversation = assistant_memory.owned_conversation(db, user.id, identifier)
    conversation.summary_failure = None
    db.commit()
    return {"status": "ready", "note": "Summary will be retried with the next submitted question"}


@router.get("/assistant/workspace/conversations/{identifier}/search")
def search(identifier: str, query: str = Query("", max_length=300), before_message_id: str | None = None,
           user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return {"items": assistant_memory.search(db, user.id, identifier, query, before_message_id)}


@router.post("/assistant/workspace/conversations/{identifier}/continue", status_code=201)
def continue_chat(identifier: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    source = assistant_memory.owned_conversation(db, user.id, identifier)
    summary = assistant_memory.latest_summary(db, identifier)
    if not summary:
        raise HTTPException(409, "No saved summary is available")
    row = Conversation(user_id=user.id, title="Continued: " + source.title[:244])
    db.add(row)
    db.flush()
    db.add(ConversationSummary(conversation_id=row.id, version=1, covered_through_message_id=None,
                              content_encrypted=encrypt_secret(decrypt_secret(summary.content_encrypted)),
                              policy_version=selected_policy()["version"]))
    _, uncovered = assistant_memory.retained_history(db, identifier, None)
    for message in assistant_memory.recent_window(uncovered, selected_policy()["recent"]):
        context = json.loads(message.context_json)
        context["continued_from_message_id"] = message.id
        db.add(AssistantMessage(conversation_id=row.id, role=message.role, content=message.content,
            context_json=json.dumps(context), evidence_json=message.evidence_json,
            tool_trace_json=message.tool_trace_json, outcome=message.outcome, created_at=message.created_at))
    db.commit()
    return {"id": row.id, "title": row.title}


class ConversationRename(BaseModel):
    title: str = Field(min_length=1, max_length=255)


@router.patch("/assistant/workspace/conversations/{identifier}")
def rename_chat(identifier: str, payload: ConversationRename, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    conversation = assistant_memory.owned_conversation(db, user.id, identifier)
    title = payload.title.strip()
    if not title:
        raise HTTPException(422, "Title is required")
    conversation.title = title
    db.commit()
    return {"id": conversation.id, "title": conversation.title}


def _delete_rows(db, table, condition):
    """Delete rows and everything that references them through foreign keys, children first."""
    for child in Base.metadata.sorted_tables:
        for fk in child.foreign_keys:
            if fk.column.table is table and child is not table:
                keys = select(fk.column).where(condition)
                _delete_rows(db, child, fk.parent.in_(keys))
    db.execute(delete(table).where(condition))


@router.delete("/assistant/workspace/conversations/{identifier}")
def delete_chat(identifier: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    conversation = assistant_memory.owned_conversation(db, user.id, identifier)
    active = db.scalar(select(AssistantExecution.id).where(AssistantExecution.conversation_id == identifier,
                       AssistantExecution.status.in_(["queued", "running"])))
    if active:
        raise HTTPException(409, "Stop the running answer before deleting this chat")
    table = Conversation.__table__
    _delete_rows(db, table, table.c.id == conversation.id)
    db.commit()
    return {"status": "deleted"}
