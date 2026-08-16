"""official source canary budgets and funnel timestamps

Revision ID: 0018_official_canary
Revises: 0017_evidence_history
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018_official_canary"
down_revision: str | None = "0017_evidence_history"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Workers read candidates and then join their source configuration. Acquire
    # both DDL locks up front, in that same order, so PostgreSQL cannot deadlock
    # after this migration has already altered the configuration table.
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "LOCK TABLE discovery_candidates, evidence_source_configs "
            "IN ACCESS EXCLUSIVE MODE"
        )
    with op.batch_alter_table("evidence_source_configs") as batch_op:
        batch_op.add_column(sa.Column("canary_group", sa.String(40), nullable=True))
        batch_op.add_column(sa.Column("daily_discovery_budget", sa.Integer(), nullable=False, server_default="100"))
        batch_op.add_column(sa.Column("daily_fetch_budget", sa.Integer(), nullable=False, server_default="15"))
        batch_op.add_column(sa.Column("daily_selected_budget", sa.Integer(), nullable=False, server_default="5"))
        batch_op.add_column(sa.Column("daily_storage_budget_bytes", sa.BigInteger(), nullable=False, server_default=str(100 * 1024 * 1024)))
        batch_op.add_column(sa.Column("provenance_json", sa.Text(), nullable=False, server_default="{}"))
        batch_op.add_column(sa.Column("fallback_json", sa.Text(), nullable=False, server_default="{}"))
        batch_op.create_check_constraint("ck_evidence_source_daily_discovery_positive", "daily_discovery_budget > 0")
        batch_op.create_check_constraint("ck_evidence_source_daily_fetch_positive", "daily_fetch_budget > 0")
        batch_op.create_check_constraint("ck_evidence_source_daily_selected_positive", "daily_selected_budget > 0")
        batch_op.create_check_constraint("ck_evidence_source_daily_storage_positive", "daily_storage_budget_bytes > 0")
        batch_op.create_index("ix_evidence_source_configs_canary_group", ["canary_group"])
    with op.batch_alter_table("discovery_candidates") as batch_op:
        batch_op.add_column(sa.Column("fetch_started_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("fetched_bytes", sa.BigInteger(), nullable=True))
        batch_op.add_column(sa.Column("selected_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.create_index("ix_discovery_candidate_fetch_started", ["fetch_started_at"])
        batch_op.create_index("ix_discovery_candidate_selected_at", ["selected_at"])


def downgrade() -> None:
    with op.batch_alter_table("discovery_candidates") as batch_op:
        batch_op.drop_index("ix_discovery_candidate_selected_at")
        batch_op.drop_index("ix_discovery_candidate_fetch_started")
        for column in ("selected_at", "fetched_bytes", "fetched_at", "fetch_started_at"):
            batch_op.drop_column(column)
    with op.batch_alter_table("evidence_source_configs") as batch_op:
        batch_op.drop_index("ix_evidence_source_configs_canary_group")
        for name in (
            "ck_evidence_source_daily_storage_positive",
            "ck_evidence_source_daily_selected_positive",
            "ck_evidence_source_daily_fetch_positive",
            "ck_evidence_source_daily_discovery_positive",
        ):
            batch_op.drop_constraint(name, type_="check")
        for column in (
            "fallback_json",
            "provenance_json",
            "daily_storage_budget_bytes",
            "daily_selected_budget",
            "daily_fetch_budget",
            "daily_discovery_budget",
            "canary_group",
        ):
            batch_op.drop_column(column)
