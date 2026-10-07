"""Per-document event classification and semantic event clustering inputs."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision = '0037_event_classification'
down_revision = '0036_routing_log'
branch_labels = depends_on = None

JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(), 'postgresql')


def upgrade():
    op.create_table('document_classifications',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('document_id', sa.String(36), sa.ForeignKey('documents.id'), nullable=False),
        sa.Column('content_hash', sa.String(64), nullable=False),
        sa.Column('classifier_version', sa.String(40), nullable=False),
        sa.Column('method', sa.String(20), nullable=False),
        sa.Column('model', sa.String(120)),
        sa.Column('status', sa.String(24), nullable=False),
        sa.Column('gaps', JSON_TYPE, nullable=False),
        sa.Column('output', JSON_TYPE, nullable=False),
        sa.UniqueConstraint('document_id', 'content_hash', 'classifier_version', name='uq_document_classification'))
    op.create_index('ix_document_classifications_document_id', 'document_classifications', ['document_id'])
    op.create_table('event_cluster_features',
        sa.Column('event_id', sa.String(36), sa.ForeignKey('normalized_events.id'), primary_key=True),
        sa.Column('entities', JSON_TYPE, nullable=False),
        sa.Column('reporting_period', sa.String(40)),
        sa.Column('counterparties', JSON_TYPE, nullable=False),
        sa.Column('amounts', JSON_TYPE, nullable=False),
        sa.Column('direction', sa.String(20), nullable=False),
        sa.Column('embedding_model', sa.String(120), nullable=False),
        sa.Column('embedding', JSON_TYPE, nullable=False))
    op.create_index('ix_event_cluster_features_reporting_period', 'event_cluster_features', ['reporting_period'])


def downgrade():
    op.drop_index('ix_event_cluster_features_reporting_period', table_name='event_cluster_features')
    op.drop_table('event_cluster_features')
    op.drop_index('ix_document_classifications_document_id', table_name='document_classifications')
    op.drop_table('document_classifications')
