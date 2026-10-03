"""Saved research, owner-scoped durable generation, and evidence read indexes."""

from alembic import op
import sqlalchemy as sa

revision = "0030_research_intelligence"
down_revision = "0029_assistant_tool_loop"
branch_labels = None
depends_on = None


def col(name, length=36, nullable=False, fk=None):
    args = [sa.String(length)]
    if fk:
        args.append(sa.ForeignKey(fk))
    return sa.Column(name, *args, nullable=nullable)


def common():
    return [
        sa.Column("id", sa.String(36), primary_key=True),
        col("user_id", fk="users.id"),
        col("input_hash", 64),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def model_fields():
    return [col("prompt_version", 40), col("provider", 50), col("model", 100)]


def upgrade():
    op.create_table(
        "company_exposure_profiles",
        *common(),
        col("instrument_id", fk="instruments.id"),
        *model_fields(),
        sa.Column("relationships_json", sa.Text(), nullable=False),
        sa.Column("evidence_json", sa.Text(), nullable=False),
        sa.Column("coverage_json", sa.Text(), nullable=False),
        sa.UniqueConstraint(
            "user_id",
            "instrument_id",
            "input_hash",
            "prompt_version",
            "provider",
            "model",
            name="uq_research_profile",
        ),
    )
    op.create_table(
        "company_event_briefs",
        *common(),
        col("instrument_id", fk="instruments.id"),
        col("normalized_event_id", nullable=True, fk="normalized_events.id"),
        col("raw_event_id", nullable=True, fk="events.id"),
        col("event_key", 80),
        *model_fields(),
        sa.Column("brief_json", sa.Text(), nullable=False),
        sa.Column("evidence_json", sa.Text(), nullable=False),
        sa.UniqueConstraint(
            "user_id",
            "instrument_id",
            "event_key",
            "input_hash",
            "prompt_version",
            "provider",
            "model",
            name="uq_research_brief",
        ),
    )
    op.create_table(
        "portfolio_event_snapshots",
        *common(),
        col("portfolio_id", fk="portfolios.id"),
        col("calculation_version", 40),
        col("valuation_as_of", 80, nullable=True),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.UniqueConstraint(
            "portfolio_id", "input_hash", "calculation_version", name="uq_research_snapshot"
        ),
    )
    op.create_table(
        "research_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        col("user_id", fk="users.id"),
        col("parent_id", nullable=True, fk="research_jobs.id"),
        col("portfolio_id", nullable=True, fk="portfolios.id"),
        col("instrument_id", nullable=True, fk="instruments.id"),
        col("job_type", 30),
        col("dedup_key", 160),
        col("status", 30),
        col("request_hash", 64),
        sa.Column("request_encrypted", sa.Text()),
        sa.Column("result_json", sa.Text(), nullable=False),
        sa.Column("max_calls", sa.Integer(), nullable=False),
        sa.Column("reserved_calls", sa.Integer(), nullable=False),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True)),
        col("error_code", 80, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "dedup_key", name="uq_research_job_dedup"),
    )
    op.create_table(
        "research_attempts",
        sa.Column("id", sa.String(36), primary_key=True),
        col("job_id", fk="research_jobs.id"),
        col("provider", 50),
        col("model", 100),
        col("status", 30),
        col("request_hash", 64),
        sa.Column("request_encrypted", sa.Text()),
        sa.Column("response_encrypted", sa.Text()),
        col("provider_request_id", 255, nullable=True),
        sa.Column("usage_json", sa.Text(), nullable=False),
        sa.Column("latency_ms", sa.Integer()),
        col("error_code", 80, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("job_id"),
    )
    for table, columns in {
        "company_exposure_profiles": [("user_id", "instrument_id", "generated_at")],
        "company_event_briefs": [("user_id", "instrument_id", "event_key", "generated_at")],
        "portfolio_event_snapshots": [("user_id", "portfolio_id")],
        "research_jobs": [("status", "created_at"), ("user_id", "parent_id")],
        "financial_facts": [("instrument_id", "period_end")],
        "event_entity_links": [("entity_type", "entity_key", "event_id")],
        "normalized_event_subjects": [("subject_type", "subject_key", "normalized_event_id")],
    }.items():
        for columns_tuple in columns:
            op.create_index(
                "ix_research_" + table + "_" + columns_tuple[0], table, list(columns_tuple)
            )
    # Do not silently delete pre-existing duplicate physical pages.
    duplicates = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT document_id, page_number FROM document_pages GROUP BY document_id, page_number HAVING COUNT(*) > 1 LIMIT 1"
            )
        )
        .first()
    )
    if duplicates:
        raise RuntimeError("Duplicate document pages require review before migration")
    op.create_index(
        "uq_document_physical_page", "document_pages", ["document_id", "page_number"], unique=True
    )


def downgrade():
    op.drop_index("uq_document_physical_page", table_name="document_pages")
    for table, column in [
        ("financial_facts", "instrument_id"),
        ("event_entity_links", "entity_type"),
        ("normalized_event_subjects", "subject_type"),
    ]:
        op.drop_index("ix_research_" + table + "_" + column, table_name=table)
    for table in (
        "research_attempts",
        "research_jobs",
        "portfolio_event_snapshots",
        "company_event_briefs",
        "company_exposure_profiles",
    ):
        op.drop_table(table)
