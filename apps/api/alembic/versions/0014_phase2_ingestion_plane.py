"""durable phase 2 ingestion coverage and screening

Revision ID: 0014_phase2_ingestion_plane
Revises: 0013_ingestion_observability
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_phase2_ingestion_plane"
down_revision: str | None = "0013_ingestion_observability"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ingestion_coverage",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("instrument_id", sa.String(36), sa.ForeignKey("instruments.id"), nullable=False, index=True),
        sa.Column("dataset_type", sa.String(60), nullable=False, index=True),
        sa.Column("period_key", sa.String(160), nullable=False, index=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="missing", index=True),
        sa.Column("source", sa.String(80), nullable=False, index=True),
        sa.Column("attempted_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("item_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_class", sa.String(160)),
        sa.Column("error_message", sa.Text()),
        sa.Column("diagnostics_json", sa.Text(), nullable=False, server_default="{}"),
        sa.UniqueConstraint("instrument_id", "dataset_type", "period_key", "source", name="uq_ingestion_coverage_key"),
    )
    op.create_table(
        "standardized_financial_facts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("instrument_id", sa.String(36), sa.ForeignKey("instruments.id"), nullable=False, index=True),
        sa.Column("metric", sa.String(120), nullable=False, index=True),
        sa.Column("period_type", sa.String(30), nullable=False),
        sa.Column("period_key", sa.String(40), nullable=False, index=True),
        sa.Column("period_end", sa.Date(), index=True),
        sa.Column("value", sa.Numeric(30, 8), nullable=False),
        sa.Column("unit", sa.String(40), nullable=False),
        sa.Column("currency", sa.String(10)),
        sa.Column("classification", sa.String(40), nullable=False, server_default="standardized_secondary"),
        sa.Column("source", sa.String(80), nullable=False),
        sa.Column("source_url", sa.String(1000), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("quality_status", sa.String(30), nullable=False, server_default="observed"),
        sa.UniqueConstraint("instrument_id", "metric", "period_type", "period_key", "source", name="uq_standardized_fact"),
    )
    op.create_table(
        "company_screening_snapshots",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("instrument_id", sa.String(36), sa.ForeignKey("instruments.id"), nullable=False, index=True),
        sa.Column("as_of_date", sa.Date(), nullable=False, index=True),
        sa.Column("sector", sa.String(120), index=True),
        sa.Column("score", sa.Numeric(10, 6)),
        sa.Column("sector_percentile", sa.Numeric(10, 6)),
        sa.Column("completeness", sa.Numeric(10, 6), nullable=False),
        sa.Column("screenable", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("promoted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("growth_flag", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("metrics_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("reasons_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("instrument_id", "as_of_date", name="uq_company_screening_date"),
    )
    with op.batch_alter_table("financial_facts") as batch:
        batch.add_column(sa.Column("source_label", sa.String(255)))
        batch.add_column(sa.Column("extraction_method", sa.String(80)))
        batch.add_column(sa.Column("confidence", sa.Numeric(8, 6)))
        batch.add_column(sa.Column("diagnostics_json", sa.Text(), nullable=False, server_default="{}"))


def downgrade() -> None:
    with op.batch_alter_table("financial_facts") as batch:
        batch.drop_column("diagnostics_json")
        batch.drop_column("confidence")
        batch.drop_column("extraction_method")
        batch.drop_column("source_label")
    op.drop_table("company_screening_snapshots")
    op.drop_table("standardized_financial_facts")
    op.drop_table("ingestion_coverage")
