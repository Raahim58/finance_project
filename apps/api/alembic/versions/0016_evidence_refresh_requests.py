"""evidence refresh request ledger

Revision ID: 0016_evidence_refresh_requests
Revises: 0015_global_evidence_v1
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016_evidence_refresh_requests"
down_revision: str | None = "0015_global_evidence_v1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "evidence_refresh_requests",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("requested_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("request_type", sa.String(length=20), nullable=False),
        sa.Column("scope_key", sa.String(length=160), nullable=False),
        sa.Column("query_text", sa.String(length=500), nullable=True),
        sa.Column("source_keys_json", sa.Text(), nullable=False, server_default='["gdelt"]'),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="queued"),
        sa.Column("priority_class", sa.String(length=20), nullable=False, server_default="live"),
        sa.Column("max_candidates", sa.Integer(), nullable=False),
        sa.Column("discovered_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("selected_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duplicate_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rejected_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_class", sa.String(length=160), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("request_type IN ('targeted', 'historical')", name="ck_evidence_refresh_request_type"),
        sa.CheckConstraint("status IN ('queued', 'running', 'processing', 'complete', 'partial', 'failed')", name="ck_evidence_refresh_status"),
        sa.CheckConstraint("priority_class IN ('live', 'historical')", name="ck_evidence_refresh_priority"),
        sa.CheckConstraint("max_candidates > 0", name="ck_evidence_refresh_limit_positive"),
        sa.ForeignKeyConstraint(["requested_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_evidence_refresh_user_created", "evidence_refresh_requests", ["requested_by_user_id", "created_at"])
    op.create_index("ix_evidence_refresh_status_priority", "evidence_refresh_requests", ["status", "priority_class", "created_at"])
    op.create_index(op.f("ix_evidence_refresh_requests_requested_by_user_id"), "evidence_refresh_requests", ["requested_by_user_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_evidence_refresh_requests_requested_by_user_id"), table_name="evidence_refresh_requests")
    op.drop_index("ix_evidence_refresh_status_priority", table_name="evidence_refresh_requests")
    op.drop_index("ix_evidence_refresh_user_created", table_name="evidence_refresh_requests")
    op.drop_table("evidence_refresh_requests")
