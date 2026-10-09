"""Persist sourced company website icons; no browser-side discovery."""
from alembic import op
import sqlalchemy as sa

revision = '0038_company_marks'
down_revision = '0037_event_classification'
branch_labels = depends_on = None


def upgrade():
    op.create_table('company_marks',
        sa.Column('symbol', sa.String(30), primary_key=True),
        sa.Column('website', sa.String(500)),
        sa.Column('profile_source_url', sa.String(500), nullable=False),
        sa.Column('image_source_url', sa.String(1000)),
        sa.Column('content', sa.LargeBinary()),
        sa.Column('sha256', sa.String(64)),
        sa.Column('status', sa.String(24), nullable=False),
        sa.Column('checked_at', sa.DateTime(timezone=True), nullable=False))


def downgrade():
    op.drop_table('company_marks')
