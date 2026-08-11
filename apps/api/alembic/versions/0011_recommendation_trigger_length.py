"""widen recommendation trigger for monitoring deduplication keys

Revision ID: 0011_recommendation_trigger
Revises: 0010_backend_hardening
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_recommendation_trigger"
down_revision: str | None = "0010_backend_hardening"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("recommendations") as batch_op:
        batch_op.alter_column(
            "trigger",
            existing_type=sa.String(80),
            type_=sa.String(160),
            existing_nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("recommendations") as batch_op:
        batch_op.alter_column(
            "trigger",
            existing_type=sa.String(160),
            type_=sa.String(80),
            existing_nullable=False,
        )
