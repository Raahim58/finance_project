"""phase 7a canonical intelligence context durability

Revision ID: 0025_phase7a_canonical_context
Revises: 0024_phase6_event_intelligence
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0025_phase7a_canonical_context"
down_revision: str | None = "0024_phase6_event_intelligence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "context_deficiencies",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("entity_type", sa.String(40), nullable=False),
        sa.Column("entity_key", sa.String(160), nullable=False),
        sa.Column("category", sa.String(80), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("occurrence_count", sa.Integer(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("fingerprint", name="uq_context_deficiency_fingerprint"),
    )
    op.create_index("ix_context_deficiencies_fingerprint", "context_deficiencies", ["fingerprint"])
    op.create_index("ix_context_deficiencies_entity_key", "context_deficiencies", ["entity_key"])
    op.create_index("ix_context_deficiencies_category", "context_deficiencies", ["category"])
    op.create_index("ix_context_deficiencies_status", "context_deficiencies", ["status"])

    op.create_table(
        "context_ingestion_work",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "deficiency_id",
            sa.String(36),
            sa.ForeignKey("context_deficiencies.id"),
            nullable=False,
        ),
        sa.Column("family", sa.String(40), nullable=False),
        sa.Column("mode", sa.String(40), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("linked_work_json", sa.Text(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text()),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("terminal_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("deficiency_id", name="uq_context_ingestion_work_deficiency"),
    )
    op.create_index("ix_context_ingestion_work_deficiency_id", "context_ingestion_work", ["deficiency_id"])
    op.create_index("ix_context_ingestion_work_family", "context_ingestion_work", ["family"])
    op.create_index("ix_context_ingestion_work_status", "context_ingestion_work", ["status"])

    op.create_table(
        "context_refresh_requests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("context_id", sa.String(64), nullable=False),
        sa.Column("request_json", sa.Text(), nullable=False),
        sa.Column("deficiency_ids_json", sa.Text(), nullable=False),
        sa.Column("work_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("rebuild_count", sa.Integer(), nullable=False),
        sa.Column("needs_rebuild", sa.Boolean(), nullable=False),
        sa.Column("terminal_at", sa.DateTime(timezone=True)),
        sa.Column("notified_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_context_refresh_requests_user_id", "context_refresh_requests", ["user_id"])
    op.create_index("ix_context_refresh_requests_context_id", "context_refresh_requests", ["context_id"])
    op.create_index("ix_context_refresh_requests_status", "context_refresh_requests", ["status"])

    op.create_table(
        "intelligence_context_receipts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("context_id", sa.String(64), nullable=False),
        sa.Column("contract_version", sa.String(30), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("receipt_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_intelligence_context_receipts_user_id", "intelligence_context_receipts", ["user_id"])
    op.create_index("ix_intelligence_context_receipts_context_id", "intelligence_context_receipts", ["context_id"])
    op.create_index("ix_intelligence_context_receipts_content_hash", "intelligence_context_receipts", ["content_hash"])

    op.create_table(
        "context_refresh_notifications",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "refresh_request_id",
            sa.String(36),
            sa.ForeignKey("context_refresh_requests.id"),
            nullable=False,
        ),
        sa.Column(
            "receipt_id",
            sa.String(36),
            sa.ForeignKey("intelligence_context_receipts.id"),
            nullable=False,
        ),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("context_id", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint(
            "refresh_request_id", name="uq_context_refresh_notification_request"
        ),
    )
    op.create_index("ix_context_refresh_notifications_refresh_request_id", "context_refresh_notifications", ["refresh_request_id"])
    op.create_index("ix_context_refresh_notifications_receipt_id", "context_refresh_notifications", ["receipt_id"])
    op.create_index("ix_context_refresh_notifications_user_id", "context_refresh_notifications", ["user_id"])
    op.create_index("ix_context_refresh_notifications_context_id", "context_refresh_notifications", ["context_id"])
    op.create_index("ix_context_refresh_notifications_status", "context_refresh_notifications", ["status"])


def downgrade() -> None:
    op.drop_table("context_refresh_notifications")
    op.drop_table("intelligence_context_receipts")
    op.drop_table("context_refresh_requests")
    op.drop_table("context_ingestion_work")
    op.drop_table("context_deficiencies")
