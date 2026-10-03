"""Durable API execution and separately committed attempt accounting."""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, Index, text
from sqlalchemy.orm import Mapped, mapped_column
from app.db.session import Base


def now():
    return datetime.now(UTC)


class AssistantExecution(Base):
    __tablename__ = "assistant_executions"
    __table_args__ = (UniqueConstraint("user_id", "client_request_id"),
        Index("uq_assistant_active_conversation", "conversation_id", unique=True,
              postgresql_where=text("status IN ('queued', 'running')"), sqlite_where=text("status IN ('queued', 'running')")),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    client_request_id: Mapped[str] = mapped_column(String(100))
    request_hash: Mapped[str] = mapped_column(String(64))
    request_encrypted: Mapped[str] = mapped_column(Text)
    transcript_encrypted: Mapped[str | None] = mapped_column(Text)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("assistant_conversations.id"))
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    event_sequence: Mapped[int] = mapped_column(Integer, default=0)
    policy_json: Mapped[str] = mapped_column(Text, default="{}")
    accounting_json: Mapped[str] = mapped_column(Text, default="{}")
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    response_json: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(String(80))
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    repair_count: Mapped[int] = mapped_column(Integer, default=0)
    revision_count: Mapped[int] = mapped_column(Integer, default=0)
    reserved_input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AssistantAttempt(Base):
    __tablename__ = "assistant_attempts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    execution_id: Mapped[str] = mapped_column(ForeignKey("assistant_executions.id"), index=True)
    operation: Mapped[str] = mapped_column(String(80))
    provider: Mapped[str] = mapped_column(String(50))
    model: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(30), default="sent")
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    payload_encrypted: Mapped[str | None] = mapped_column(Text)
    payload_eviction: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AssistantStage(Base):
    __tablename__ = "assistant_stages"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    execution_id: Mapped[str] = mapped_column(ForeignKey("assistant_executions.id"), index=True)
    operation: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(30), default="running")
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
