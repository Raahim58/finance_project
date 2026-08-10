"""optimizer audit runs only; ordinary analytics remain calculated/cached

Revision ID: 0007_quant_optimizer
Revises: 0006_domain_data
"""
from collections.abc import Sequence
import sqlalchemy as sa
from alembic import op

revision: str = "0007_quant_optimizer"
down_revision: str | None = "0006_domain_data"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table("optimizer_runs",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("portfolio_id", sa.String(36), sa.ForeignKey("portfolios.id"), nullable=False),
        sa.Column("objective", sa.String(40), nullable=False), sa.Column("expected_return_method", sa.String(40)), sa.Column("data_cutoff", sa.Date(), nullable=False),
        sa.Column("input_json", sa.Text(), nullable=False), sa.Column("result_json", sa.Text(), nullable=False), sa.Column("status", sa.String(30), nullable=False),
        sa.Column("diagnostics_json", sa.Text(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_optimizer_runs_portfolio_id", "optimizer_runs", ["portfolio_id"])


def downgrade() -> None:
    op.drop_index("ix_optimizer_runs_portfolio_id", table_name="optimizer_runs")
    op.drop_table("optimizer_runs")
