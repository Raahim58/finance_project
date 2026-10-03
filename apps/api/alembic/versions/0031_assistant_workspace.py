"""Persistent streaming assistant workspace.

Revision ID: 0031
Revises: 0030
"""
from alembic import op
import sqlalchemy as sa
revision = "0031_assistant_workspace"
down_revision = "0030_research_intelligence"
branch_labels = depends_on = None


def upgrade():
    op.add_column("assistant_conversations", sa.Column("summary_failure", sa.String(80)))
    for name, kind, default in [("context_json", sa.Text(), "{}"), ("execution_id", sa.String(36), None), ("outcome", sa.String(30), None)]:
        op.add_column("assistant_messages", sa.Column(name, kind, nullable=default is None, server_default=default))
    op.create_index("ix_assistant_messages_execution_id", "assistant_messages", ["execution_id"])
    for name, kind, default in [("event_sequence", sa.Integer(), "0"), ("policy_json", sa.Text(), "{}"), ("accounting_json", sa.Text(), "{}"), ("cancel_requested_at", sa.DateTime(timezone=True), None)]:
        op.add_column("assistant_executions", sa.Column(name, kind, nullable=default is None, server_default=default))
    op.create_table("assistant_execution_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("execution_id", sa.String(36), sa.ForeignKey("assistant_executions.id"), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False), sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("payload_encrypted", sa.Text(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("execution_id", "sequence"))
    op.create_index("ix_assistant_execution_events_execution_id", "assistant_execution_events", ["execution_id"])
    op.create_table("assistant_conversation_summaries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("conversation_id", sa.String(36), sa.ForeignKey("assistant_conversations.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("covered_through_message_id", sa.String(36), sa.ForeignKey("assistant_messages.id")),
        sa.Column("content_encrypted", sa.Text(), nullable=False), sa.Column("policy_version", sa.String(50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("conversation_id", "version"), sa.UniqueConstraint("conversation_id", "covered_through_message_id"))
    op.create_index("ix_assistant_conversation_summaries_conversation_id", "assistant_conversation_summaries", ["conversation_id"])
    op.create_table("assistant_provider_queue",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("credential_hash", sa.String(64), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_assistant_provider_queue_credential_hash", "assistant_provider_queue", ["credential_hash"])
    op.create_index("ix_assistant_provider_queue_expires_at", "assistant_provider_queue", ["expires_at"])
    if op.get_bind().dialect.name == "postgresql":
        op.execute("CREATE INDEX ix_assistant_history_text ON assistant_messages USING gin (to_tsvector('simple'::regconfig, content))")
    op.create_index("uq_assistant_active_conversation", "assistant_executions", ["conversation_id"], unique=True,
                    postgresql_where=sa.text("status IN ('queued', 'running')"), sqlite_where=sa.text("status IN ('queued', 'running')"))


def downgrade():
    if op.get_bind().dialect.name == "postgresql":
        op.drop_index("ix_assistant_history_text", table_name="assistant_messages")
    op.drop_index("uq_assistant_active_conversation", table_name="assistant_executions")
    for table in ["assistant_provider_queue", "assistant_conversation_summaries", "assistant_execution_events"]:
        op.drop_table(table)
    op.drop_index("ix_assistant_messages_execution_id", table_name="assistant_messages")
    for table, columns in [("assistant_executions", ["event_sequence", "policy_json", "accounting_json", "cancel_requested_at"]), ("assistant_messages", ["context_json", "execution_id", "outcome"]), ("assistant_conversations", ["summary_failure"])]:
        for column in columns:
            op.drop_column(table, column)
