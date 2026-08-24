"""phase 5 retrieval foundation

Revision ID: 0023_phase5_retrieval_foundation
Revises: 0022_classify_stored_evidence
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0023_phase5_retrieval_foundation"
down_revision: str | None = "0022_classify_stored_evidence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("source_tier", sa.Integer(), nullable=False, server_default="3"))
    op.add_column("documents", sa.Column("data_status", sa.String(30), nullable=False, server_default="observed"))
    op.create_index("ix_documents_source_tier", "documents", ["source_tier"])
    op.create_index("ix_documents_data_status", "documents", ["data_status"])

    op.add_column("document_chunks", sa.Column("content_type", sa.String(20), nullable=False, server_default="narrative"))
    op.add_column("document_chunks", sa.Column("embedding_model", sa.String(160), nullable=False, server_default="unknown"))
    op.add_column("document_chunks", sa.Column("embedding_index_version", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("document_chunks", sa.Column("embedding_status", sa.String(20), nullable=False, server_default="indexed"))
    op.create_index("ix_document_chunks_content_type", "document_chunks", ["content_type"])
    op.create_index("ix_document_chunks_embedding_model", "document_chunks", ["embedding_model"])
    op.create_index("ix_document_chunks_embedding_index_version", "document_chunks", ["embedding_index_version"])
    op.create_index("ix_document_chunks_embedding_status", "document_chunks", ["embedding_status"])

    op.execute(
        "UPDATE documents SET data_status='synthetic_demo' "
        "WHERE document_type='synthetic_demo_facts' OR source_name='Deterministic Demo Seed'"
    )
    op.execute(
        "UPDATE documents SET data_status='user_upload', source_tier=4 "
        "WHERE owner_user_id IS NOT NULL AND data_status='observed'"
    )
    op.execute(
        "UPDATE documents SET document_type='announcement' "
        "WHERE document_type='selected_evidence' AND EXISTS ("
        "SELECT 1 FROM event_sources JOIN events ON events.id=event_sources.event_id "
        "WHERE event_sources.document_id=documents.id AND events.event_type='announcement')"
    )
    op.execute(
        "UPDATE documents SET document_type='news' "
        "WHERE document_type='selected_evidence' AND EXISTS ("
        "SELECT 1 FROM event_sources JOIN events ON events.id=event_sources.event_id "
        "WHERE event_sources.document_id=documents.id AND events.event_type='news')"
    )
    op.execute("UPDATE documents SET document_type='quarterly_report' WHERE document_type='interim_report'")


def downgrade() -> None:
    op.drop_index("ix_document_chunks_embedding_status", table_name="document_chunks")
    op.drop_index("ix_document_chunks_embedding_index_version", table_name="document_chunks")
    op.drop_index("ix_document_chunks_embedding_model", table_name="document_chunks")
    op.drop_index("ix_document_chunks_content_type", table_name="document_chunks")
    op.drop_column("document_chunks", "embedding_status")
    op.drop_column("document_chunks", "embedding_index_version")
    op.drop_column("document_chunks", "embedding_model")
    op.drop_column("document_chunks", "content_type")
    op.drop_index("ix_documents_data_status", table_name="documents")
    op.drop_index("ix_documents_source_tier", table_name="documents")
    op.drop_column("documents", "data_status")
    op.drop_column("documents", "source_tier")
