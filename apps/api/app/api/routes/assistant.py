import json

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.orchestrator import run_assistant
from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.models.intelligence_context import ContextRefreshRequest
from app.models.workstation import AssistantMessage, Conversation
from app.schemas.assistant import AssistantMessageCreate, AssistantResponse, ConversationCreate
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
    return await run_assistant(db, current_user, payload)


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
    return await run_assistant(db, current_user, payload, conversation_id)
