"""Indexed multi-sector and topic evidence tags, without rebuilding embeddings."""
from alembic import op
import sqlalchemy as sa
revision = '0032_document_evidence_tags'
down_revision = '0031_assistant_workspace'
branch_labels = depends_on = None


def upgrade():
    op.create_table('document_evidence_tags',
        sa.Column('id',sa.String(36),primary_key=True),
        sa.Column('document_id',sa.String(36),sa.ForeignKey('documents.id',ondelete='CASCADE'),nullable=False),
        sa.Column('kind',sa.String(20),nullable=False),
        sa.Column('value',sa.String(120),nullable=False),
        sa.Column('basis',sa.String(40),nullable=False),
        sa.UniqueConstraint('document_id','kind','value'))
    op.create_index('ix_document_evidence_tags_document_id','document_evidence_tags',['document_id'])
    op.create_index('ix_document_evidence_tags_lookup','document_evidence_tags',['kind','value','document_id'])


def downgrade():
    op.drop_table('document_evidence_tags')
