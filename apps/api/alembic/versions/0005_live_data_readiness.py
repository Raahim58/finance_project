"""live data readiness

Revision ID: 0005_live_data
Revises: 0004_phase_4
Create Date: 2026-06-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_live_data"
down_revision: str | None = "0004_phase_4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("portfolios", sa.Column("source_mode", sa.String(length=20), nullable=False, server_default="manual"))
    op.add_column(
        "portfolios",
        sa.Column("provider_name", sa.String(length=80), nullable=False, server_default="ManualPortfolioProvider"),
    )
    op.add_column("portfolios", sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        "market_ingestion_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("mode", sa.String(length=20), nullable=False),
        sa.Column("source", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("latest_trade_date", sa.Date(), nullable=True),
        sa.Column("records_written", sa.Integer(), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_market_ingestion_runs_mode"), "market_ingestion_runs", ["mode"], unique=False)
    op.create_index(op.f("ix_market_ingestion_runs_source"), "market_ingestion_runs", ["source"], unique=False)
    op.create_index(op.f("ix_market_ingestion_runs_status"), "market_ingestion_runs", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_market_ingestion_runs_status"), table_name="market_ingestion_runs")
    op.drop_index(op.f("ix_market_ingestion_runs_source"), table_name="market_ingestion_runs")
    op.drop_index(op.f("ix_market_ingestion_runs_mode"), table_name="market_ingestion_runs")
    op.drop_table("market_ingestion_runs")
    op.drop_column("portfolios", "last_synced_at")
    op.drop_column("portfolios", "provider_name")
    op.drop_column("portfolios", "source_mode")
