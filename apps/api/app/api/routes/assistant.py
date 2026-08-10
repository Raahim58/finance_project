import json

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.orchestrator import run_assistant
from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.models.workstation import AssistantMessage, Conversation
from app.schemas.assistant import AssistantMessageCreate, AssistantResponse, ConversationCreate
from app.services.portfolio_service import get_portfolio_or_404

router = APIRouter()


@router.get("/assistant/conversations")
def conversations(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return [{"id": row.id, "portfolio_id": row.portfolio_id, "title": row.title, "created_at": row.created_at} for row in db.scalars(select(Conversation).where(Conversation.user_id == current_user.id).order_by(Conversation.created_at.desc()))]


@router.post("/assistant/conversations", status_code=201)
def create_conversation(payload: ConversationCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if payload.portfolio_id: get_portfolio_or_404(db, current_user, payload.portfolio_id)
    row = Conversation(user_id=current_user.id, portfolio_id=payload.portfolio_id, title=payload.title)
    db.add(row); db.commit(); db.refresh(row)
    return {"id": row.id, "portfolio_id": row.portfolio_id, "title": row.title, "created_at": row.created_at}


@router.get("/assistant/conversations/{conversation_id}/messages")
def messages(conversation_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    conversation = db.scalar(select(Conversation).where(Conversation.id == conversation_id, Conversation.user_id == current_user.id))
    if conversation is None: return []
    return [{"id": row.id, "role": row.role, "content": row.content, "evidence": json.loads(row.evidence_json), "tool_trace": json.loads(row.tool_trace_json), "created_at": row.created_at} for row in db.scalars(select(AssistantMessage).where(AssistantMessage.conversation_id == conversation.id).order_by(AssistantMessage.created_at))]


@router.post("/assistant/messages", response_model=AssistantResponse, status_code=201)
async def message(payload: AssistantMessageCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return await run_assistant(db, current_user, payload)


@router.post("/assistant/conversations/{conversation_id}/messages", response_model=AssistantResponse, status_code=201)
async def conversation_message(conversation_id: str, payload: AssistantMessageCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return await run_assistant(db, current_user, payload, conversation_id)
