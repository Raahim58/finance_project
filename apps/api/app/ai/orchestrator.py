"""Assistant entry points backed by the single durable model-directed tool loop."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.tool_loop import run_tool_loop
from app.models.portfolio import Portfolio
from app.models.user import User
from app.models.workstation import Conversation
from app.schemas.assistant import AssistantMessageCreate
from app.services.portfolio_service import get_portfolio_or_404


def _conversation(
    db: Session,
    user: User,
    conversation_id: str | None,
    payload: AssistantMessageCreate,
) -> Conversation:
    if conversation_id:
        conversation = db.scalar(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.user_id == user.id,
            )
        )
        if conversation is None:
            from fastapi import HTTPException

            raise HTTPException(404, "Conversation not found")
        return conversation
    conversation = Conversation(
        user_id=user.id,
        portfolio_id=payload.portfolio_id,
        title=payload.question.strip()[:255],
    )
    db.add(conversation)
    db.flush()
    return conversation


def _resolved_portfolio(
    db: Session,
    user: User,
    conversation: Conversation,
    requested_portfolio_id: str | None,
) -> Portfolio | None:
    trusted_id = requested_portfolio_id or conversation.portfolio_id
    if trusted_id:
        portfolio = get_portfolio_or_404(db, user, trusted_id)
        if portfolio.archived_at is not None:
            from fastapi import HTTPException

            raise HTTPException(409, "Archived portfolios cannot be analyzed")
        return portfolio
    return db.scalar(
        select(Portfolio).where(
            Portfolio.user_id == user.id,
            Portfolio.is_default.is_(True),
            Portfolio.archived_at.is_(None),
        )
    )


async def run_assistant(
    db: Session,
    user: User,
    payload: AssistantMessageCreate,
    conversation_id: str | None = None,
    *,
    accepted: bool = False,
):
    return await run_tool_loop(db, user, payload, conversation_id, accepted=accepted)
