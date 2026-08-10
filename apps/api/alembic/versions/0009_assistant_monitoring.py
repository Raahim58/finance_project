"""auditable recommendations and user monitoring rules

Revision ID: 0009_assistant_monitoring
Revises: 0008_research_scenarios
"""
from collections.abc import Sequence
import sqlalchemy as sa
from alembic import op

revision: str = "0009_assistant_monitoring"
down_revision: str | None = "0008_research_scenarios"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table("recommendations",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("portfolio_id", sa.String(36), sa.ForeignKey("portfolios.id"), nullable=False), sa.Column("trigger", sa.String(80), nullable=False),
        sa.Column("evidence_json", sa.Text(), nullable=False), sa.Column("message", sa.Text(), nullable=False), sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("monitoring_rules",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("portfolio_id", sa.String(36), sa.ForeignKey("portfolios.id"), nullable=False), sa.Column("rule_type", sa.String(60), nullable=False),
        sa.Column("threshold_json", sa.Text(), nullable=False), sa.Column("enabled", sa.Boolean(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_recommendations_user_id", "recommendations", ["user_id"])
    op.create_index("ix_monitoring_rules_user_id", "monitoring_rules", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_monitoring_rules_user_id", table_name="monitoring_rules"); op.drop_table("monitoring_rules")
    op.drop_index("ix_recommendations_user_id", table_name="recommendations"); op.drop_table("recommendations")
