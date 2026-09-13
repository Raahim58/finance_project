"""Encrypted Assistant tool-loop transcript checkpoint.

Revision ID: 0029_assistant_tool_loop
Revises: 0028_assistant_executions
"""

from alembic import op
import sqlalchemy as sa


revision = "0029_assistant_tool_loop"
down_revision = "0028_assistant_executions"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("assistant_executions") as batch_op:
        batch_op.add_column(sa.Column("transcript_encrypted", sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table("assistant_executions") as batch_op:
        batch_op.drop_column("transcript_encrypted")
