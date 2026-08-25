"""phase 7b canonical context consumer linkage

Revision ID: 0026_phase7b_context_consumers
Revises: 0025_phase7a_canonical_context
"""

from alembic import op
import sqlalchemy as sa


revision = "0026_phase7b_context_consumers"
down_revision = "0025_phase7a_canonical_context"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("intelligence_context_receipts") as batch:
        batch.add_column(sa.Column("consumer_type", sa.String(30)))
        batch.add_column(sa.Column("consumer_key", sa.String(160)))
        batch.add_column(sa.Column("output_id", sa.String(36)))
        batch.create_index("ix_intelligence_context_receipts_consumer_type", ["consumer_type"])
        batch.create_index("ix_intelligence_context_receipts_consumer_key", ["consumer_key"])
        batch.create_index("ix_intelligence_context_receipts_output_id", ["output_id"])

    with op.batch_alter_table("assistant_messages") as batch:
        batch.add_column(
            sa.Column("message_kind", sa.String(30), nullable=False, server_default="answer")
        )
        batch.add_column(sa.Column("parent_message_id", sa.String(36)))
        batch.add_column(sa.Column("context_receipt_id", sa.String(36)))
        batch.create_foreign_key(
            "fk_assistant_messages_parent_message",
            "assistant_messages",
            ["parent_message_id"],
            ["id"],
        )
        batch.create_foreign_key(
            "fk_assistant_messages_context_receipt",
            "intelligence_context_receipts",
            ["context_receipt_id"],
            ["id"],
        )
        batch.create_index("ix_assistant_messages_parent_message_id", ["parent_message_id"])
        batch.create_index("ix_assistant_messages_context_receipt_id", ["context_receipt_id"])

    with op.batch_alter_table("context_refresh_requests") as batch:
        batch.add_column(sa.Column("consumer_type", sa.String(30)))
        batch.add_column(sa.Column("consumer_key", sa.String(160)))
        batch.add_column(sa.Column("source_message_id", sa.String(36)))
        batch.create_foreign_key(
            "fk_context_refresh_source_message",
            "assistant_messages",
            ["source_message_id"],
            ["id"],
        )
        batch.create_index("ix_context_refresh_requests_consumer_type", ["consumer_type"])
        batch.create_index("ix_context_refresh_requests_consumer_key", ["consumer_key"])
        batch.create_index("ix_context_refresh_requests_source_message_id", ["source_message_id"])


def downgrade() -> None:
    with op.batch_alter_table("context_refresh_requests") as batch:
        batch.drop_index("ix_context_refresh_requests_source_message_id")
        batch.drop_index("ix_context_refresh_requests_consumer_key")
        batch.drop_index("ix_context_refresh_requests_consumer_type")
        batch.drop_constraint("fk_context_refresh_source_message", type_="foreignkey")
        batch.drop_column("source_message_id")
        batch.drop_column("consumer_key")
        batch.drop_column("consumer_type")

    with op.batch_alter_table("assistant_messages") as batch:
        batch.drop_index("ix_assistant_messages_context_receipt_id")
        batch.drop_index("ix_assistant_messages_parent_message_id")
        batch.drop_constraint("fk_assistant_messages_context_receipt", type_="foreignkey")
        batch.drop_constraint("fk_assistant_messages_parent_message", type_="foreignkey")
        batch.drop_column("context_receipt_id")
        batch.drop_column("parent_message_id")
        batch.drop_column("message_kind")

    with op.batch_alter_table("intelligence_context_receipts") as batch:
        batch.drop_index("ix_intelligence_context_receipts_output_id")
        batch.drop_index("ix_intelligence_context_receipts_consumer_key")
        batch.drop_index("ix_intelligence_context_receipts_consumer_type")
        batch.drop_column("output_id")
        batch.drop_column("consumer_key")
        batch.drop_column("consumer_type")
