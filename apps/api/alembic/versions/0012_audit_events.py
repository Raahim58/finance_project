"""add audit_events table and alert acknowledgement actor/note columns

Revision ID: 0012_audit_events
Revises: 0011_recommendation_trigger
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_audit_events"
down_revision: str | None = "0011_recommendation_trigger"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("portfolio_id", sa.String(36), sa.ForeignKey("portfolios.id"), nullable=True, index=True),
        sa.Column("event_type", sa.String(60), nullable=False, index=True),
        sa.Column("entity_type", sa.String(60), nullable=False),
        sa.Column("entity_id", sa.String(36), nullable=False, index=True),
        sa.Column("entity_version", sa.Integer(), nullable=True),
        sa.Column("previous_state_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("new_state_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("data_cutoff", sa.Date(), nullable=True),
        sa.Column("source", sa.String(160), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, index=True),
    )
    with op.batch_alter_table("alerts") as batch_op:
        batch_op.add_column(sa.Column("acknowledged_by_user_id", sa.String(36), nullable=True))
        batch_op.add_column(sa.Column("acknowledgement_note", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("alerts") as batch_op:
        batch_op.drop_column("acknowledgement_note")
        batch_op.drop_column("acknowledged_by_user_id")
    op.drop_table("audit_events")
