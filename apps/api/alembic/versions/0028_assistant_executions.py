"""Durable assistant executions and encrypted attempt diagnostics.

Revision ID: 0028_assistant_executions
Revises: 0027_llm_invocation_diagnostics
"""
from alembic import op
import sqlalchemy as sa

revision = "0028_assistant_executions"
down_revision = "0027_llm_invocation_diagnostics"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("assistant_executions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("client_request_id", sa.String(100), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("request_encrypted", sa.Text(), nullable=False),
        sa.Column("conversation_id", sa.String(36), sa.ForeignKey("assistant_conversations.id"), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("response_json", sa.Text()),
        sa.Column("error_code", sa.String(80)),
        *[sa.Column(name, sa.Integer(), nullable=False, server_default="0") for name in
          ("retry_count", "repair_count", "revision_count", "reserved_input_tokens")],
        *[sa.Column(name, sa.DateTime(timezone=True), nullable=name != "created_at") for name in
          ("created_at", "started_at", "heartbeat_at", "completed_at", "received_at")],
        sa.UniqueConstraint("user_id", "client_request_id"))
    op.create_index("ix_assistant_executions_user_id", "assistant_executions", ["user_id"])
    op.create_index("ix_assistant_executions_status", "assistant_executions", ["status"])
    op.create_table("assistant_attempts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("execution_id", sa.String(36), sa.ForeignKey("assistant_executions.id"), nullable=False),
        sa.Column("operation", sa.String(80), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("model", sa.String(120), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=False),
        sa.Column("payload_encrypted", sa.Text()),
        sa.Column("payload_eviction", sa.String(40)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)))
    op.create_index("ix_assistant_attempts_execution_id", "assistant_attempts", ["execution_id"])
    op.create_table("assistant_stages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("execution_id", sa.String(36), sa.ForeignKey("assistant_executions.id"), nullable=False),
        sa.Column("operation", sa.String(80), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)))
    op.create_index("ix_assistant_stages_execution_id", "assistant_stages", ["execution_id"])
    with op.batch_alter_table("llm_invocations") as batch_op:
        batch_op.add_column(sa.Column("execution_id", sa.String(36), nullable=True))
        batch_op.create_foreign_key(
            "fk_llm_invocations_execution_id",
            "assistant_executions",
            ["execution_id"],
            ["id"],
        )
    op.create_index(
        "ix_llm_invocations_execution_id", "llm_invocations", ["execution_id"]
    )
    # Historical invocations remain untouched and readable.


def downgrade():
    op.drop_index("ix_llm_invocations_execution_id", table_name="llm_invocations")
    with op.batch_alter_table("llm_invocations") as batch_op:
        batch_op.drop_constraint("fk_llm_invocations_execution_id", type_="foreignkey")
        batch_op.drop_column("execution_id")
    op.drop_table("assistant_stages")
    op.drop_table("assistant_attempts")
    op.drop_table("assistant_executions")
