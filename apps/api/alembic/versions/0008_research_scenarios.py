"""scenario audit and document visibility

Revision ID: 0008_research_scenarios
Revises: 0007_quant_optimizer
"""
from collections.abc import Sequence
import sqlalchemy as sa
from alembic import op

revision: str = "0008_research_scenarios"
down_revision: str | None = "0007_quant_optimizer"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Columns are added without inline FKs for SQLite migration compatibility;
    # retrieval services enforce ownership and PostgreSQL can add constraints later.
    op.add_column("documents", sa.Column("owner_user_id", sa.String(36)))
    op.add_column("documents", sa.Column("portfolio_id", sa.String(36)))
    op.add_column("documents", sa.Column("visibility", sa.String(20), nullable=False, server_default="public"))
    op.create_index("ix_documents_owner_user_id", "documents", ["owner_user_id"])
    op.create_index("ix_documents_portfolio_id", "documents", ["portfolio_id"])
    op.create_index("ix_documents_visibility", "documents", ["visibility"])
    op.create_table("scenario_runs",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("portfolio_id", sa.String(36), sa.ForeignKey("portfolios.id"), nullable=False),
        sa.Column("name", sa.String(160), nullable=False), sa.Column("shocks_json", sa.Text(), nullable=False), sa.Column("result_json", sa.Text(), nullable=False),
        sa.Column("data_cutoff", sa.Date(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_scenario_runs_portfolio_id", "scenario_runs", ["portfolio_id"])


def downgrade() -> None:
    op.drop_index("ix_scenario_runs_portfolio_id", table_name="scenario_runs"); op.drop_table("scenario_runs")
    for index in ["ix_documents_visibility", "ix_documents_portfolio_id", "ix_documents_owner_user_id"]: op.drop_index(index, table_name="documents")
    for name in ["visibility", "portfolio_id", "owner_user_id"]: op.drop_column("documents", name)
