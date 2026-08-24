"""phase 6 deterministic event intelligence

Revision ID: 0024_phase6_event_intelligence
Revises: 0023_phase5_retrieval_foundation
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0024_phase6_event_intelligence"
down_revision: str | None = "0023_phase5_retrieval_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "normalized_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("event_type", sa.String(60), nullable=False),
        sa.Column("classification_status", sa.String(20), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_time_end", sa.DateTime(timezone=True)),
        sa.Column("cluster_key", sa.String(64), nullable=False),
        sa.Column("factor", sa.String(80)),
        sa.Column("geography", sa.String(80)),
        sa.Column("magnitude", sa.Numeric(20, 6)),
        sa.Column("magnitude_unit", sa.String(30)),
        sa.Column("materiality", sa.String(20), nullable=False),
        sa.Column("confidence", sa.Numeric(8, 6), nullable=False),
        sa.Column("freshness_score", sa.Numeric(8, 6), nullable=False),
        sa.Column("freshness_status", sa.String(20), nullable=False),
        sa.Column("detection_version", sa.String(40), nullable=False),
        sa.Column("details_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("cluster_key", name="uq_normalized_event_cluster_key"),
    )
    op.create_index("ix_normalized_events_event_type", "normalized_events", ["event_type"])
    op.create_index("ix_normalized_events_classification_status", "normalized_events", ["classification_status"])
    op.create_index("ix_normalized_events_occurred_at", "normalized_events", ["occurred_at"])
    op.create_index("ix_normalized_events_factor", "normalized_events", ["factor"])
    op.create_index("ix_normalized_events_geography", "normalized_events", ["geography"])
    op.create_index("ix_normalized_events_materiality", "normalized_events", ["materiality"])
    op.create_index("ix_normalized_events_freshness_status", "normalized_events", ["freshness_status"])
    op.create_index("ix_normalized_event_type_occurred", "normalized_events", ["event_type", "occurred_at"])
    op.create_index("ix_normalized_event_factor_occurred", "normalized_events", ["factor", "occurred_at"])

    op.create_table(
        "normalized_event_evidence",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("normalized_event_id", sa.String(36), sa.ForeignKey("normalized_events.id"), nullable=False),
        sa.Column("raw_event_id", sa.String(36), sa.ForeignKey("events.id"), nullable=False, unique=True),
        sa.Column("evidence_role", sa.String(30), nullable=False),
        sa.Column("linked_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_normalized_event_evidence_normalized_event_id", "normalized_event_evidence", ["normalized_event_id"])
    op.create_index("ix_normalized_event_evidence_raw_event_id", "normalized_event_evidence", ["raw_event_id"])

    op.create_table(
        "normalized_event_subjects",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("normalized_event_id", sa.String(36), sa.ForeignKey("normalized_events.id"), nullable=False),
        sa.Column("subject_type", sa.String(30), nullable=False),
        sa.Column("subject_key", sa.String(160), nullable=False),
        sa.Column("link_method", sa.String(40), nullable=False),
        sa.Column("confidence", sa.Numeric(8, 6), nullable=False),
        sa.Column("is_direct", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("normalized_event_id", "subject_type", "subject_key", name="uq_normalized_event_subject"),
    )
    op.create_index("ix_normalized_event_subjects_normalized_event_id", "normalized_event_subjects", ["normalized_event_id"])
    op.create_index("ix_normalized_event_subjects_subject_type", "normalized_event_subjects", ["subject_type"])
    op.create_index("ix_normalized_event_subjects_subject_key", "normalized_event_subjects", ["subject_key"])


def downgrade() -> None:
    op.drop_table("normalized_event_subjects")
    op.drop_table("normalized_event_evidence")
    op.drop_table("normalized_events")
