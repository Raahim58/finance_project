"""research facts, events, scenarios, and document visibility

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
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        from pgvector.sqlalchemy import Vector
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
        op.add_column("document_chunks", sa.Column("embedding_vector", Vector(384)))
        op.create_index("ix_document_chunks_embedding_vector_hnsw", "document_chunks", ["embedding_vector"], postgresql_using="hnsw", postgresql_ops={"embedding_vector": "vector_cosine_ops"})
    else:
        op.add_column("document_chunks", sa.Column("embedding_vector", sa.Text()))
    for column in [
        sa.Column("owner_user_id", sa.String(36)),
        sa.Column("portfolio_id", sa.String(36)),
        sa.Column("visibility", sa.String(20), nullable=False, server_default="public"),
        sa.Column("extraction_version", sa.String(80)),
        sa.Column("parser_version", sa.String(80)),
        sa.Column("artifact_id", sa.String(36)),
    ]:
        op.add_column("documents", column)
    for name in ["owner_user_id", "portfolio_id", "visibility", "artifact_id"]:
        op.create_index(f"ix_documents_{name}", "documents", [name])

    op.create_table(
        "macro_series",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("key", sa.String(160), nullable=False, unique=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("unit", sa.String(60), nullable=False),
        sa.Column("frequency", sa.String(30), nullable=False),
        sa.Column("source_id", sa.String(36), sa.ForeignKey("data_sources.id"), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=False),
    )
    op.create_table(
        "macro_observations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("series_id", sa.String(36), sa.ForeignKey("macro_series.id"), nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column("release_at", sa.DateTime(timezone=True)),
        sa.Column("value", sa.Numeric(24, 8), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("artifact_id", sa.String(36), sa.ForeignKey("source_artifacts.id")),
        sa.Column("is_selected", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("series_id", "effective_date", "release_at", name="uq_macro_revision"),
    )
    op.create_table(
        "financial_facts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("instrument_id", sa.String(36), sa.ForeignKey("instruments.id"), nullable=False),
        sa.Column("taxonomy_key", sa.String(160), nullable=False),
        sa.Column("period_type", sa.String(30), nullable=False),
        sa.Column("period_start", sa.Date()),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("filing_date", sa.Date()),
        sa.Column("value", sa.Numeric(30, 8), nullable=False),
        sa.Column("unit", sa.String(40), nullable=False),
        sa.Column("currency", sa.String(10)),
        sa.Column("consolidated", sa.Boolean(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.String(36), sa.ForeignKey("documents.id")),
        sa.Column("page_number", sa.Integer()),
    )
    op.create_table(
        "corporate_actions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("instrument_id", sa.String(36), sa.ForeignKey("instruments.id"), nullable=False),
        sa.Column("action_type", sa.String(40), nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column("ex_date", sa.Date()),
        sa.Column("payment_date", sa.Date()),
        sa.Column("details_json", sa.Text(), nullable=False),
        sa.Column("artifact_id", sa.String(36), sa.ForeignKey("source_artifacts.id")),
    )
    op.create_table(
        "events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("event_type", sa.String(60), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("materiality", sa.String(20)),
        sa.Column("direction", sa.String(20)),
        sa.Column("confidence", sa.Numeric(8, 6)),
        sa.Column("details_json", sa.Text(), nullable=False),
    )
    op.create_table(
        "event_sources",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("event_id", sa.String(36), sa.ForeignKey("events.id"), nullable=False),
        sa.Column("source_url", sa.String(1000), nullable=False),
        sa.Column("source_name", sa.String(120), nullable=False),
        sa.Column("artifact_id", sa.String(36), sa.ForeignKey("source_artifacts.id")),
        sa.Column("document_id", sa.String(36), sa.ForeignKey("documents.id")),
    )
    op.create_table(
        "event_entity_links",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("event_id", sa.String(36), sa.ForeignKey("events.id"), nullable=False),
        sa.Column("entity_type", sa.String(30), nullable=False),
        sa.Column("entity_key", sa.String(160), nullable=False),
        sa.Column("link_method", sa.String(30), nullable=False),
        sa.Column("confidence", sa.Numeric(8, 6), nullable=False),
    )
    op.create_table(
        "scenario_definitions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("portfolio_id", sa.String(36), sa.ForeignKey("portfolios.id")),
        sa.Column("owner_user_id", sa.String(36), sa.ForeignKey("users.id")),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("scenario_type", sa.String(30), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("assumptions_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "scenario_shocks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("scenario_definition_id", sa.String(36), sa.ForeignKey("scenario_definitions.id"), nullable=False),
        sa.Column("target_type", sa.String(30), nullable=False),
        sa.Column("target_key", sa.String(160), nullable=False),
        sa.Column("shock_value", sa.Numeric(14, 8), nullable=False),
        sa.Column("unit", sa.String(30), nullable=False),
    )
    op.create_table(
        "scenario_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("portfolio_id", sa.String(36), sa.ForeignKey("portfolios.id"), nullable=False),
        sa.Column("scenario_definition_id", sa.String(36), sa.ForeignKey("scenario_definitions.id")),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("shocks_json", sa.Text(), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=False),
        sa.Column("data_cutoff", sa.Date(), nullable=False),
        sa.Column("assumptions_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    for table in [
        "scenario_runs", "scenario_shocks", "scenario_definitions", "event_entity_links",
        "event_sources", "events", "corporate_actions", "financial_facts",
        "macro_observations", "macro_series",
    ]:
        op.drop_table(table)
    for name in ["artifact_id", "visibility", "portfolio_id", "owner_user_id"]:
        op.drop_index(f"ix_documents_{name}", table_name="documents")
    for name in ["artifact_id", "parser_version", "extraction_version", "visibility", "portfolio_id", "owner_user_id"]:
        op.drop_column("documents", name)
    if op.get_bind().dialect.name == "postgresql":
        op.drop_index("ix_document_chunks_embedding_vector_hnsw", table_name="document_chunks")
    op.drop_column("document_chunks", "embedding_vector")
