"""Cached AI market and portfolio briefs."""
from alembic import op
import sqlalchemy as sa

revision = '0039_ai_briefs'
down_revision = '0038_company_marks'
branch_labels = depends_on = None


def upgrade():
    op.create_table('ai_briefs',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id'), nullable=False, index=True),
        sa.Column('input_hash', sa.String(64), nullable=False),
        sa.Column('generated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('scope', sa.String(20), nullable=False, index=True),
        sa.Column('scope_key', sa.String(64), nullable=False, server_default=''),
        sa.Column('provider', sa.String(50), nullable=False),
        sa.Column('model', sa.String(100), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='running'),
        sa.Column('brief_json', sa.Text()), sa.Column('facts_json', sa.Text()),
        sa.Column('error_code', sa.String(60)),
        sa.UniqueConstraint('user_id', 'scope', 'scope_key', 'input_hash', name='uq_ai_brief'))


def downgrade():
    op.drop_table('ai_briefs')
