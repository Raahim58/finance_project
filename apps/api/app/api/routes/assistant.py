import json

from fastapi import APIRouter, Depends, HTTPException
from uuid import uuid4
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.models.intelligence_context import ContextRefreshRequest
from app.models.workstation import AssistantMessage, Conversation
from app.schemas.assistant import AssistantMessageCreate, AssistantResponse, ConversationCreate, AssistantRunCreate
from app.services import assistant_execution as execution_service
from app.services.assistant_diagnostics import inspect_execution, provider_error_detail
from app.models.assistant_execution import AssistantExecution, now as execution_now
from app.services.portfolio_service import get_portfolio_or_404
from app.services.context_refresh_service import reconcile_pending_contexts

router = APIRouter()


@router.get("/assistant/conversations")
def conversations(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return [
        {
            "id": row.id,
            "portfolio_id": row.portfolio_id,
            "title": row.title,
            "created_at": row.created_at,
        }
        for row in db.scalars(
            select(Conversation)
            .where(Conversation.user_id == current_user.id)
            .order_by(Conversation.created_at.desc())
        )
    ]


@router.post("/assistant/conversations", status_code=201)
def create_conversation(
    payload: ConversationCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if payload.portfolio_id:
        get_portfolio_or_404(db, current_user, payload.portfolio_id)
    row = Conversation(
        user_id=current_user.id, portfolio_id=payload.portfolio_id, title=payload.title
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {
        "id": row.id,
        "portfolio_id": row.portfolio_id,
        "title": row.title,
        "created_at": row.created_at,
    }


@router.get("/assistant/conversations/{conversation_id}/messages")
def messages(
    conversation_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    conversation = db.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id, Conversation.user_id == current_user.id
        )
    )
    if conversation is None:
        return []
    inactive_refreshes = list(
        db.scalars(
            select(ContextRefreshRequest).where(
                ContextRefreshRequest.user_id == current_user.id,
                ContextRefreshRequest.consumer_type == "assistant",
                ContextRefreshRequest.consumer_key == conversation.id,
                ContextRefreshRequest.active.is_(False),
                ContextRefreshRequest.rebuild_count == 0,
            )
        )
    )
    if inactive_refreshes:
        for refresh in inactive_refreshes:
            refresh.active = True
        db.commit()
        reconcile_pending_contexts(
            db, refresh_ids=[refresh.id for refresh in inactive_refreshes]
        )
    return [
        {
            "id": row.id,
            "role": row.role,
            "content": row.content,
            "message_kind": row.message_kind,
            "parent_message_id": row.parent_message_id,
            "context_receipt_id": row.context_receipt_id,
            "evidence": json.loads(row.evidence_json),
            "tool_trace": json.loads(row.tool_trace_json),
            "created_at": row.created_at,
        }
        for row in db.scalars(
            select(AssistantMessage)
            .where(AssistantMessage.conversation_id == conversation.id)
            .order_by(AssistantMessage.created_at)
        )
    ]


@router.post("/assistant/messages", response_model=AssistantResponse, status_code=201)
async def message(
    payload: AssistantMessageCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return await compatible_message(db, current_user, payload)


@router.post(
    "/assistant/conversations/{conversation_id}/messages",
    response_model=AssistantResponse,
    status_code=201,
)
async def conversation_message(
    conversation_id: str,
    payload: AssistantMessageCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return await compatible_message(db, current_user, payload, conversation_id)


@router.post("/assistant/runs", status_code=202)
async def create_run(
    payload: AssistantRunCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = execution_service.accept(db, current_user,
        AssistantMessageCreate.model_validate(payload.model_dump()),
        payload.client_request_id, payload.conversation_id)
    if row.status == "queued":
        execution_service.schedule(row.id)
    return {"execution_id": row.id, "status": row.status}


@router.get("/assistant/runs/{execution_id}")
def run_status(execution_id: str, current_user: User = Depends(get_current_user),
               db: Session = Depends(get_db)):
    row = execution_service.owned(db, current_user.id, execution_id)
    return {"execution_id": row.id, "status": row.status, "error_code": row.error_code,
            "error_detail": provider_error_detail(db, row.id),
            "response": json.loads(row.response_json) if row.response_json else None}


@router.post("/assistant/runs/{execution_id}/receipt", status_code=204)
def receipt(execution_id: str, current_user: User = Depends(get_current_user),
            db: Session = Depends(get_db)):
    row = execution_service.owned(db, current_user.id, execution_id)
    if row.response_json and row.received_at is None:
        row.received_at = execution_now()
        db.commit()


@router.get("/assistant/diagnostics")
def diagnostic_list(status: str | None = None, current_user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    statement = select(AssistantExecution).where(AssistantExecution.user_id == current_user.id)
    if status:
        statement = statement.where(AssistantExecution.status == status)
    rows = db.scalars(statement.order_by(AssistantExecution.created_at.desc()).limit(100))
    return [inspect_execution(db, row) for row in rows]


@router.get("/assistant/diagnostics-aggregate")
def diagnostic_aggregate(current_user: User = Depends(get_current_user),
                         db: Session = Depends(get_db)):
    rows = db.execute(
        select(AssistantExecution.status, func.count(AssistantExecution.id))
        .where(AssistantExecution.user_id == current_user.id)
        .group_by(AssistantExecution.status)
    )
    counts = {status: count for status, count in rows}
    return {"execution_count": sum(counts.values()), "outcomes": counts}


@router.get("/assistant/diagnostics/{execution_id}")
@router.get("/assistant/diagnostics/{execution_id}/export")
def diagnostic(execution_id: str, compare_to: str | None = None,
               current_user: User = Depends(get_current_user),
               db: Session = Depends(get_db)):
    current = inspect_execution(db, execution_service.owned(db, current_user.id, execution_id))
    if not compare_to:
        return current
    other = inspect_execution(db, execution_service.owned(db, current_user.id, compare_to))
    return {
        "current": current,
        "comparison": other,
        "delta": {
            "reserved_input_tokens": current["reserved_input_tokens"]
            - other["reserved_input_tokens"],
            "attempt_count": len(current["attempts"]) - len(other["attempts"]),
            "queue_ms": None if current["queue_ms"] is None or other["queue_ms"] is None
            else current["queue_ms"] - other["queue_ms"],
        },
    }


async def compatible_message(db, user, payload, conversation_id=None):
    row = execution_service.accept(db, user, payload, str(uuid4()), conversation_id)
    identifier = row.id
    # Compatibility callers await delivery; the independent task survives disconnects.
    execution_service.schedule(identifier)
    import asyncio
    await asyncio.shield(execution_service._tasks[identifier])
    db.expire_all()
    row = execution_service.owned(db, user.id, identifier)
    if row.response_json:
        return json.loads(row.response_json)
    status_code = (
        int(row.error_code.rsplit("_", 1)[1])
        if row.error_code and row.error_code.startswith("provider_http_")
        else 503
    )
    raise HTTPException(
        status_code,
        {
            "execution_id": identifier,
            "error_code": row.error_code,
            "error_detail": provider_error_detail(db, identifier),
        },
    )
