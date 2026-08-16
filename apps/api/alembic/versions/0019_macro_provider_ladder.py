"""add source-independent macro provider ladders and observation provenance

Revision ID: 0019_macro_provider_ladder
Revises: 0018_official_source_canary
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019_macro_provider_ladder"
down_revision: str | None = "0018_official_canary"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "macro_series_providers",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("series_id", sa.String(36), sa.ForeignKey("macro_series.id"), nullable=False),
        sa.Column("data_source_id", sa.String(36), sa.ForeignKey("data_sources.id"), nullable=False),
        sa.Column("provider_key", sa.String(160), nullable=False),
        sa.Column("source_series_id", sa.String(255), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("authority", sa.String(30), nullable=False),
        sa.Column("retrieval_method", sa.String(40), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("metadata_json", sa.Text(), nullable=False, server_default="{}"),
        sa.UniqueConstraint("series_id", "provider_key", name="uq_macro_series_provider"),
    )
    op.create_index("ix_macro_series_providers_series_id", "macro_series_providers", ["series_id"])
    op.create_index("ix_macro_series_providers_data_source_id", "macro_series_providers", ["data_source_id"])
    op.create_index("ix_macro_series_providers_provider_key", "macro_series_providers", ["provider_key"])

    with op.batch_alter_table("macro_observations") as batch_op:
        batch_op.drop_constraint("uq_macro_revision", type_="unique")
        batch_op.add_column(sa.Column("provider_id", sa.String(36), nullable=True))
        batch_op.add_column(sa.Column("source_series_id", sa.String(255), nullable=True))
        batch_op.add_column(sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("vintage_date", sa.Date(), nullable=True))
        batch_op.add_column(sa.Column("authority", sa.String(30), nullable=True))
        batch_op.add_column(sa.Column("confidence", sa.Numeric(6, 5), nullable=True))
        batch_op.add_column(sa.Column("selection_reason", sa.Text(), nullable=True))
        batch_op.create_foreign_key(
            "fk_macro_observations_provider_id",
            "macro_series_providers",
            ["provider_id"],
            ["id"],
        )
        batch_op.create_index("ix_macro_observations_provider_id", ["provider_id"])
        batch_op.create_index("ix_macro_observations_source_series_id", ["source_series_id"])
        batch_op.create_unique_constraint(
            "uq_macro_provider_revision",
            ["series_id", "effective_date", "provider_id", "release_at"],
        )


def downgrade() -> None:
    with op.batch_alter_table("macro_observations") as batch_op:
        batch_op.drop_constraint("uq_macro_provider_revision", type_="unique")
        batch_op.drop_index("ix_macro_observations_source_series_id")
        batch_op.drop_index("ix_macro_observations_provider_id")
        batch_op.drop_constraint("fk_macro_observations_provider_id", type_="foreignkey")
        batch_op.drop_column("selection_reason")
        batch_op.drop_column("confidence")
        batch_op.drop_column("authority")
        batch_op.drop_column("vintage_date")
        batch_op.drop_column("retrieved_at")
        batch_op.drop_column("source_series_id")
        batch_op.drop_column("provider_id")
        batch_op.create_unique_constraint(
            "uq_macro_revision", ["series_id", "effective_date", "release_at"]
        )
    op.drop_index("ix_macro_series_providers_provider_key", table_name="macro_series_providers")
    op.drop_index("ix_macro_series_providers_data_source_id", table_name="macro_series_providers")
    op.drop_index("ix_macro_series_providers_series_id", table_name="macro_series_providers")
    op.drop_table("macro_series_providers")
