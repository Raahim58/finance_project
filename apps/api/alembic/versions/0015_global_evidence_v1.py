"""global evidence v1 persistence foundation

Revision ID: 0015_global_evidence_v1
Revises: 0014_phase2_ingestion_plane
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0015_global_evidence_v1"
down_revision: str | None = "0014_phase2_ingestion_plane"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


CANDIDATE_STATUSES = (
    "discovered",
    "fetch_ready",
    "evaluating",
    "clustered",
    "selected",
    "duplicate",
    "rejected",
    "failed",
    "expired",
)


def upgrade() -> None:
    op.create_table(
        "evidence_source_configs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "data_source_id",
            sa.String(36),
            sa.ForeignKey("data_sources.id"),
            nullable=False,
        ),
        sa.Column("source_key", sa.String(80), nullable=False),
        sa.Column("source_tier", sa.String(30), nullable=False, server_default="other"),
        sa.Column("roles_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("categories_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("discovery_methods_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("fetch_methods_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("languages_json", sa.Text(), nullable=False, server_default='["en"]'),
        sa.Column("poll_interval_seconds", sa.Integer(), nullable=False),
        sa.Column("historical_days", sa.Integer()),
        sa.Column("config_version", sa.String(40), nullable=False, server_default="evidence-v1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "poll_interval_seconds > 0", name="ck_evidence_source_poll_positive"
        ),
        sa.CheckConstraint(
            "historical_days IS NULL OR historical_days >= 0",
            name="ck_evidence_source_history_nonnegative",
        ),
        sa.UniqueConstraint("data_source_id", name="uq_evidence_source_data_source"),
        sa.UniqueConstraint("source_key", name="uq_evidence_source_key"),
    )
    op.create_table(
        "evidence_source_states",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "source_config_id",
            sa.String(36),
            sa.ForeignKey("evidence_source_configs.id"),
            nullable=False,
        ),
        sa.Column("cursor_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("etag", sa.String(255)),
        sa.Column("last_modified", sa.String(255)),
        sa.Column("next_poll_at", sa.DateTime(timezone=True)),
        sa.Column("last_attempted_at", sa.DateTime(timezone=True)),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error_class", sa.String(160)),
        sa.Column("last_error_message", sa.Text()),
        sa.Column("diagnostics_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("source_config_id", name="uq_evidence_source_state_config"),
    )
    op.create_index(
        "ix_evidence_source_state_next_poll",
        "evidence_source_states",
        ["next_poll_at"],
    )
    op.create_table(
        "discovery_candidates",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "source_config_id",
            sa.String(36),
            sa.ForeignKey("evidence_source_configs.id"),
            nullable=False,
        ),
        sa.Column("external_id", sa.String(255)),
        sa.Column("observed_url", sa.String(1000), nullable=False),
        sa.Column("canonical_url", sa.String(1000)),
        sa.Column("canonical_url_hash", sa.String(64)),
        sa.Column("headline", sa.String(500), nullable=False),
        sa.Column("normalized_headline_hash", sa.String(64)),
        sa.Column("publisher", sa.String(160), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("discovered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("discovery_method", sa.String(40), nullable=False),
        sa.Column("discovery_query", sa.String(255)),
        sa.Column("topic", sa.String(120)),
        sa.Column("language", sa.String(20)),
        sa.Column("status", sa.String(30), nullable=False, server_default="discovered"),
        sa.Column("artifact_id", sa.String(36), sa.ForeignKey("source_artifacts.id")),
        sa.Column("event_id", sa.String(36), sa.ForeignKey("events.id")),
        sa.Column("body_sha256", sa.String(64)),
        sa.Column("simhash", sa.String(16)),
        sa.Column("relevance_score", sa.Numeric(8, 6)),
        sa.Column("novelty_score", sa.Numeric(8, 6)),
        sa.Column("quality_score", sa.Numeric(8, 6)),
        sa.Column("scoring_reasons_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("metadata_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column(
            "configuration_version", sa.String(40), nullable=False, server_default="evidence-v1"
        ),
        sa.Column("parser_version", sa.String(80)),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("last_error_class", sa.String(160)),
        sa.Column("last_error_message", sa.Text()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN (" + ", ".join(f"'{value}'" for value in CANDIDATE_STATUSES) + ")",
            name="ck_discovery_candidate_status",
        ),
        sa.CheckConstraint("retry_count >= 0", name="ck_discovery_candidate_retry_nonnegative"),
        sa.UniqueConstraint(
            "source_config_id", "external_id", name="uq_discovery_candidate_external_id"
        ),
        sa.UniqueConstraint(
            "canonical_url_hash", name="uq_discovery_candidate_canonical_url_hash"
        ),
    )
    for name, columns in (
        ("ix_discovery_candidate_status_attempt", ["status", "next_attempt_at"]),
        ("ix_discovery_candidate_source_published", ["source_config_id", "published_at"]),
        ("ix_discovery_candidate_topic_published", ["topic", "published_at"]),
        ("ix_discovery_candidate_lease", ["lease_expires_at"]),
        ("ix_discovery_candidate_event", ["event_id"]),
        ("ix_discovery_candidate_artifact", ["artifact_id"]),
        ("ix_discovery_candidate_body_hash", ["body_sha256"]),
        ("ix_discovery_candidate_headline_hash", ["normalized_headline_hash"]),
        ("ix_discovery_candidate_simhash", ["simhash"]),
    ):
        op.create_index(name, "discovery_candidates", columns)

    with op.batch_alter_table("events") as batch:
        batch.add_column(sa.Column("event_time_end", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("cluster_key", sa.String(64)))
        batch.add_column(sa.Column("topic", sa.String(120)))
        batch.add_column(sa.Column("geography", sa.String(80)))
        batch.add_column(
            sa.Column("cluster_status", sa.String(30), nullable=False, server_default="active")
        )
        batch.add_column(
            sa.Column(
                "cluster_version",
                sa.String(40),
                nullable=False,
                server_default="deterministic-v1",
            )
        )
        batch.add_column(
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            )
        )
        batch.create_unique_constraint("uq_event_cluster_key", ["cluster_key"])
        batch.create_index("ix_event_topic_occurred", ["topic", "occurred_at"])
        batch.create_index("ix_event_geography_occurred", ["geography", "occurred_at"])

    with op.batch_alter_table("event_sources") as batch:
        batch.add_column(sa.Column("candidate_id", sa.String(36)))
        batch.add_column(sa.Column("published_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("evidence_role", sa.String(30)))
        batch.add_column(
            sa.Column("selection_status", sa.String(20), nullable=False, server_default="legacy")
        )
        batch.add_column(sa.Column("relevance_score", sa.Numeric(8, 6)))
        batch.add_column(sa.Column("novelty_score", sa.Numeric(8, 6)))
        batch.add_column(sa.Column("quality_score", sa.Numeric(8, 6)))
        batch.add_column(
            sa.Column("selection_reasons_json", sa.Text(), nullable=False, server_default="[]")
        )
        batch.create_foreign_key(
            "fk_event_source_candidate", "discovery_candidates", ["candidate_id"], ["id"]
        )
        batch.create_unique_constraint("uq_event_source_candidate", ["candidate_id"])
        batch.create_unique_constraint("uq_event_source_url", ["event_id", "source_url"])
        batch.create_index(
            "ix_event_source_selection",
            ["event_id", "selection_status", "evidence_role"],
        )
        batch.create_index("ix_event_source_published_at", ["published_at"])


def downgrade() -> None:
    with op.batch_alter_table("event_sources") as batch:
        batch.drop_index("ix_event_source_published_at")
        batch.drop_index("ix_event_source_selection")
        batch.drop_constraint("uq_event_source_url", type_="unique")
        batch.drop_constraint("uq_event_source_candidate", type_="unique")
        batch.drop_constraint("fk_event_source_candidate", type_="foreignkey")
        for name in (
            "selection_reasons_json",
            "quality_score",
            "novelty_score",
            "relevance_score",
            "selection_status",
            "evidence_role",
            "published_at",
            "candidate_id",
        ):
            batch.drop_column(name)

    with op.batch_alter_table("events") as batch:
        batch.drop_index("ix_event_geography_occurred")
        batch.drop_index("ix_event_topic_occurred")
        batch.drop_constraint("uq_event_cluster_key", type_="unique")
        for name in (
            "updated_at",
            "cluster_version",
            "cluster_status",
            "geography",
            "topic",
            "cluster_key",
            "event_time_end",
        ):
            batch.drop_column(name)

    for name in (
        "ix_discovery_candidate_simhash",
        "ix_discovery_candidate_headline_hash",
        "ix_discovery_candidate_body_hash",
        "ix_discovery_candidate_artifact",
        "ix_discovery_candidate_event",
        "ix_discovery_candidate_lease",
        "ix_discovery_candidate_topic_published",
        "ix_discovery_candidate_source_published",
        "ix_discovery_candidate_status_attempt",
    ):
        op.drop_index(name, table_name="discovery_candidates")
    op.drop_table("discovery_candidates")
    op.drop_index("ix_evidence_source_state_next_poll", table_name="evidence_source_states")
    op.drop_table("evidence_source_states")
    op.drop_table("evidence_source_configs")
