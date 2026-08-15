"""conservative evidence history budgets and progress

Revision ID: 0017_evidence_history
Revises: 0016_evidence_refresh_requests
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017_evidence_history"
down_revision: str | None = "0016_evidence_refresh_requests"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "evidence_source_states",
        sa.Column("healthy_since", sa.DateTime(timezone=True), nullable=True),
    )
    with op.batch_alter_table("evidence_refresh_requests") as batch_op:
        batch_op.add_column(sa.Column("preset_key", sa.String(length=40), nullable=True))
        batch_op.add_column(sa.Column("date_from", sa.Date(), nullable=True))
        batch_op.add_column(sa.Column("date_to", sa.Date(), nullable=True))
        batch_op.add_column(
            sa.Column("progress_json", sa.Text(), nullable=False, server_default="{}")
        )
        batch_op.add_column(
            sa.Column("fetch_budget", sa.Integer(), nullable=False, server_default="50")
        )
        batch_op.add_column(
            sa.Column(
                "storage_budget_bytes",
                sa.BigInteger(),
                nullable=False,
                server_default=str(250 * 1024 * 1024),
            )
        )
        batch_op.add_column(
            sa.Column("fetched_count", sa.Integer(), nullable=False, server_default="0")
        )
        batch_op.add_column(
            sa.Column("fetched_bytes", sa.BigInteger(), nullable=False, server_default="0")
        )
        batch_op.create_check_constraint(
            "ck_evidence_refresh_fetch_budget_positive", "fetch_budget > 0"
        )
        batch_op.create_check_constraint(
            "ck_evidence_refresh_storage_budget_positive", "storage_budget_bytes > 0"
        )


def downgrade() -> None:
    with op.batch_alter_table("evidence_refresh_requests") as batch_op:
        batch_op.drop_constraint(
            "ck_evidence_refresh_storage_budget_positive", type_="check"
        )
        batch_op.drop_constraint("ck_evidence_refresh_fetch_budget_positive", type_="check")
        for column in (
            "fetched_bytes",
            "fetched_count",
            "storage_budget_bytes",
            "fetch_budget",
            "progress_json",
            "date_to",
            "date_from",
            "preset_key",
        ):
            batch_op.drop_column(column)
    op.drop_column("evidence_source_states", "healthy_since")
