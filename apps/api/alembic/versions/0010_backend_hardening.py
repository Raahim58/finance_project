"""backend accounting, canonical data, and calendar hardening

Revision ID: 0010_backend_hardening
Revises: 0009_assistant_monitoring
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_backend_hardening"
down_revision: str | None = "0009_assistant_monitoring"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "exchange_calendar_days",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("exchange_code", sa.String(20), nullable=False),
        sa.Column("session_date", sa.Date(), nullable=False),
        sa.Column("is_session", sa.Boolean(), nullable=False),
        sa.Column("open_time", sa.String(10)),
        sa.Column("close_time", sa.String(10)),
        sa.Column("reason", sa.String(255)),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("artifact_id", sa.String(36), sa.ForeignKey("source_artifacts.id")),
        sa.UniqueConstraint("exchange_code", "session_date", name="uq_exchange_calendar_day"),
    )
    op.create_index("ix_exchange_calendar_days_exchange_code", "exchange_calendar_days", ["exchange_code"])
    op.create_index("ix_exchange_calendar_days_session_date", "exchange_calendar_days", ["session_date"])
    op.create_index("ix_exchange_calendar_days_artifact_id", "exchange_calendar_days", ["artifact_id"])


def downgrade() -> None:
    op.drop_index("ix_exchange_calendar_days_artifact_id", table_name="exchange_calendar_days")
    op.drop_index("ix_exchange_calendar_days_session_date", table_name="exchange_calendar_days")
    op.drop_index("ix_exchange_calendar_days_exchange_code", table_name="exchange_calendar_days")
    op.drop_table("exchange_calendar_days")
