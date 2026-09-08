from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


def uuid_str() -> str:
    return str(uuid4())


class LLMInvocation(Base):
    """Bounded server-side audit metadata for one external model attempt."""

    __tablename__ = "llm_invocations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    execution_id: Mapped[str | None] = mapped_column(
        ForeignKey("assistant_executions.id"), index=True
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("assistant_conversations.id"), nullable=False, index=True
    )
    assistant_message_id: Mapped[str] = mapped_column(
        ForeignKey("assistant_messages.id"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    operation: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    http_status: Mapped[int | None] = mapped_column(Integer)
    error_type: Mapped[str | None] = mapped_column(String(160))
    error_message: Mapped[str | None] = mapped_column(Text)
    provider_request_id: Mapped[str | None] = mapped_column(String(255), index=True)
    input_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    input_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    response_excerpt: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
