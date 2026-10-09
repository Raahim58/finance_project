"""Persistent company snapshots and cited briefs on the existing research queue."""
from alembic import op
import sqlalchemy as sa
revision = '0033_company_digests'
down_revision = '0032_document_evidence_tags'
branch_labels = depends_on = None


def upgrade():
    op.create_table('company_digests',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('instrument_id', sa.String(36), sa.ForeignKey('instruments.id'), nullable=False),
        sa.Column('input_hash', sa.String(64), nullable=False),
        sa.Column('generated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('prompt_version', sa.String(40), nullable=False),
        sa.Column('provider', sa.String(50), nullable=False),
        sa.Column('model', sa.String(100), nullable=False),
        sa.Column('snapshot_json', sa.Text(), nullable=False),
        sa.Column('brief_json', sa.Text()),
        sa.UniqueConstraint('user_id','instrument_id','input_hash','prompt_version','provider','model',name='uq_company_digest'))
    op.create_index('ix_company_digests_user_id','company_digests',['user_id'])
    op.create_index('ix_company_digests_instrument_id','company_digests',['instrument_id'])


def downgrade():
    op.drop_table('company_digests')
