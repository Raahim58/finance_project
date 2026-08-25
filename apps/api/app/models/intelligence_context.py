"""Durable Phase 7A deficiency, refresh, and compact receipt records."""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


def _uuid() -> str:
    return str(uuid4())


def _now() -> datetime:
    return datetime.now(UTC)


class ContextDeficiencyRecord(Base):
    __tablename__ = "context_deficiencies"
    __table_args__ = (UniqueConstraint("fingerprint", name="uq_context_deficiency_fingerprint"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_key: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="open", nullable=False, index=True)
    occurrence_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ContextRefreshRequest(Base):
    __tablename__ = "context_refresh_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    context_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    request_json: Mapped[str] = mapped_column(Text, nullable=False)
    deficiency_ids_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    work_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    consumer_type: Mapped[str | None] = mapped_column(String(30), index=True)
    consumer_key: Mapped[str | None] = mapped_column(String(160), index=True)
    source_message_id: Mapped[str | None] = mapped_column(
        ForeignKey("assistant_messages.id"), index=True
    )
    status: Mapped[str] = mapped_column(String(30), default="pending", nullable=False, index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    rebuild_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    needs_rebuild: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    terminal_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now, nullable=False
    )


class ContextIngestionWork(Base):
    """Durable aggregate linking one deficiency to existing ingestion ledgers."""

    __tablename__ = "context_ingestion_work"
    __table_args__ = (
        UniqueConstraint("deficiency_id", name="uq_context_ingestion_work_deficiency"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    deficiency_id: Mapped[str] = mapped_column(
        ForeignKey("context_deficiencies.id"), nullable=False, index=True
    )
    family: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    mode: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="queued", nullable=False, index=True)
    linked_work_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )
    deadline_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    terminal_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now, nullable=False
    )


class IntelligenceContextReceiptRecord(Base):
    __tablename__ = "intelligence_context_receipts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    context_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    contract_version: Mapped[str] = mapped_column(String(30), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    consumer_type: Mapped[str | None] = mapped_column(String(30), index=True)
    consumer_key: Mapped[str | None] = mapped_column(String(160), index=True)
    output_id: Mapped[str | None] = mapped_column(String(36), index=True)
    receipt_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )


class ContextRefreshNotification(Base):
    """Compact durable outbox item for an active consumer's rebuilt context."""

    __tablename__ = "context_refresh_notifications"
    __table_args__ = (
        UniqueConstraint("refresh_request_id", name="uq_context_refresh_notification_request"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    refresh_request_id: Mapped[str] = mapped_column(
        ForeignKey("context_refresh_requests.id"), nullable=False, index=True
    )
    receipt_id: Mapped[str] = mapped_column(
        ForeignKey("intelligence_context_receipts.id"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    context_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False, index=True)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
