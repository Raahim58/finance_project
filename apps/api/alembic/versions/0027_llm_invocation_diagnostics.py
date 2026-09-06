"""persist bounded LLM invocation diagnostics

Revision ID: 0027_llm_invocation_diagnostics
Revises: 0026_phase7b_context_consumers
"""

from alembic import op
import sqlalchemy as sa


revision = "0027_llm_invocation_diagnostics"
down_revision = "0026_phase7b_context_consumers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "llm_invocations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "conversation_id",
            sa.String(36),
            sa.ForeignKey("assistant_conversations.id"),
            nullable=False,
        ),
        sa.Column(
            "assistant_message_id",
            sa.String(36),
            sa.ForeignKey("assistant_messages.id"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("model", sa.String(120), nullable=False),
        sa.Column("operation", sa.String(80), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("http_status", sa.Integer()),
        sa.Column("error_type", sa.String(160)),
        sa.Column("error_message", sa.Text()),
        sa.Column("provider_request_id", sa.String(255)),
        sa.Column("input_bytes", sa.Integer(), nullable=False),
        sa.Column("input_sha256", sa.String(64), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("input_tokens", sa.Integer()),
        sa.Column("output_tokens", sa.Integer()),
        sa.Column("response_excerpt", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_llm_invocations_user_id", "llm_invocations", ["user_id"])
    op.create_index(
        "ix_llm_invocations_conversation_id", "llm_invocations", ["conversation_id"]
    )
    op.create_index(
        "ix_llm_invocations_assistant_message_id",
        "llm_invocations",
        ["assistant_message_id"],
    )
    op.create_index("ix_llm_invocations_provider", "llm_invocations", ["provider"])
    op.create_index("ix_llm_invocations_status", "llm_invocations", ["status"])
    op.create_index(
        "ix_llm_invocations_provider_request_id",
        "llm_invocations",
        ["provider_request_id"],
    )


def downgrade() -> None:
    op.drop_table("llm_invocations")
