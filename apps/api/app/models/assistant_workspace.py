"""Persistent conversation memory and encrypted execution replay."""
from datetime import datetime
from uuid import uuid4
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.db.session import Base
from app.models.assistant_execution import now

class ExecutionEvent(Base):
    __tablename__ = "assistant_execution_events"
    __table_args__ = (UniqueConstraint("execution_id", "sequence"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    execution_id: Mapped[str] = mapped_column(ForeignKey("assistant_executions.id"), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(30))
    payload_encrypted: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class ConversationSummary(Base):
    __tablename__ = "assistant_conversation_summaries"
    __table_args__ = (UniqueConstraint("conversation_id", "version"), UniqueConstraint("conversation_id", "covered_through_message_id"))
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    conversation_id: Mapped[str] = mapped_column(ForeignKey("assistant_conversations.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    covered_through_message_id: Mapped[str | None] = mapped_column(ForeignKey("assistant_messages.id"))
    content_encrypted: Mapped[str] = mapped_column(Text)
    policy_version: Mapped[str] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class ProviderQueueEntry(Base):
    __tablename__ = "assistant_provider_queue"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    credential_hash: Mapped[str] = mapped_column(String(64), index=True)
    priority: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
