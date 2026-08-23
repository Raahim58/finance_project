"""add canonical ingestion accounting and source-scoped artifact identity

Revision ID: 0021_ingestion_audit_repairs
Revises: 0020_fix_macro_fiscal_series
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0021_ingestion_audit_repairs"
down_revision: str | None = "0020_fix_macro_fiscal_series"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("market_ingestion_runs", sa.Column("attempted_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("market_ingestion_runs", sa.Column("accepted_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("market_ingestion_runs", sa.Column("rejected_count", sa.Integer(), nullable=False, server_default="0"))
    if op.get_bind().dialect.name == "sqlite":
        sha_constraint = next(
            constraint
            for constraint in sa.inspect(op.get_bind()).get_unique_constraints("source_artifacts")
            if constraint.get("column_names") == ["sha256"]
        )
        with op.batch_alter_table(
            "source_artifacts",
            naming_convention={"uq": "uq_%(table_name)s_%(column_0_name)s"},
        ) as batch_op:
            batch_op.drop_constraint(
                sha_constraint.get("name") or "uq_source_artifacts_sha256",
                type_="unique",
            )
            batch_op.create_unique_constraint(
                "uq_source_artifact_capture",
                ["data_source_id", "request_fingerprint", "sha256"],
            )
    else:
        op.drop_constraint("source_artifacts_sha256_key", "source_artifacts", type_="unique")
        op.create_unique_constraint(
            "uq_source_artifact_capture",
            "source_artifacts",
            ["data_source_id", "request_fingerprint", "sha256"],
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("source_artifacts") as batch_op:
            batch_op.drop_constraint("uq_source_artifact_capture", type_="unique")
            batch_op.create_unique_constraint("source_artifacts_sha256_key", ["sha256"])
    else:
        op.drop_constraint("uq_source_artifact_capture", "source_artifacts", type_="unique")
        op.create_unique_constraint("source_artifacts_sha256_key", "source_artifacts", ["sha256"])
    op.drop_column("market_ingestion_runs", "rejected_count")
    op.drop_column("market_ingestion_runs", "accepted_count")
    op.drop_column("market_ingestion_runs", "attempted_count")
