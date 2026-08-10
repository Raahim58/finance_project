"""quant analysis and optimizer audit persistence

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
    op.create_table(
        "analysis_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("portfolio_id", sa.String(36), sa.ForeignKey("portfolios.id")),
        sa.Column("instrument_id", sa.String(36), sa.ForeignKey("instruments.id")),
        sa.Column("analysis_type", sa.String(60), nullable=False),
        sa.Column("input_fingerprint", sa.String(64), nullable=False, unique=True),
        sa.Column("data_cutoff", sa.Date(), nullable=False),
        sa.Column("estimator_json", sa.Text(), nullable=False),
        sa.Column("code_version", sa.String(80), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=False),
        sa.Column("artifact_hashes_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "optimizer_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("portfolio_id", sa.String(36), sa.ForeignKey("portfolios.id"), nullable=False),
        sa.Column("objective", sa.String(40), nullable=False),
        sa.Column("expected_return_method", sa.String(40)),
        sa.Column("ips_version_id", sa.String(36), sa.ForeignKey("portfolio_ips_versions.id")),
        sa.Column("data_cutoff", sa.Date(), nullable=False),
        sa.Column("bounds_json", sa.Text(), nullable=False),
        sa.Column("solver", sa.String(60)),
        sa.Column("seed", sa.Integer()),
        sa.Column("input_json", sa.Text(), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("diagnostics_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_optimizer_runs_portfolio_id", "optimizer_runs", ["portfolio_id"])
    op.create_table(
        "optimizer_allocations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("optimizer_run_id", sa.String(36), sa.ForeignKey("optimizer_runs.id"), nullable=False),
        sa.Column("instrument_id", sa.String(36), sa.ForeignKey("instruments.id"), nullable=False),
        sa.Column("weight", sa.Numeric(12, 8), nullable=False),
        sa.UniqueConstraint("optimizer_run_id", "instrument_id", name="uq_optimizer_instrument"),
    )


def downgrade() -> None:
    op.drop_table("optimizer_allocations")
    op.drop_index("ix_optimizer_runs_portfolio_id", table_name="optimizer_runs")
    op.drop_table("optimizer_runs")
    op.drop_table("analysis_runs")
