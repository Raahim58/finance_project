"""Weighted, indexed lexical retrieval independent of embedding availability."""
from alembic import op
import sqlalchemy as sa
revision='0035_pipeline_text_index'
down_revision='0034_pipeline_restoration'
branch_labels=depends_on=None


def upgrade():
    if op.get_bind().dialect.name!='postgresql': return
    # The trigger also handles ordinary/manual document paths and title edits.
    op.execute("ALTER TABLE document_chunks ADD COLUMN search_vector tsvector")
    op.execute('''CREATE FUNCTION pipeline_chunk_search_vector() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            NEW.search_vector := setweight(to_tsvector('english',coalesce((SELECT title FROM documents WHERE id=NEW.document_id),'')),'A')
                || setweight(to_tsvector('english',coalesce(NEW.section_title,'')),'B')
                || setweight(to_tsvector('english',coalesce(NEW.chunk_text,'')),'C');
            RETURN NEW;
        END $$''')
    op.execute('''CREATE TRIGGER pipeline_chunk_search BEFORE INSERT OR UPDATE OF chunk_text,section_title,document_id
        ON document_chunks FOR EACH ROW EXECUTE FUNCTION pipeline_chunk_search_vector()''')
    op.execute('''CREATE FUNCTION pipeline_document_search_vector() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            UPDATE document_chunks SET chunk_text=chunk_text WHERE document_id=NEW.id;
            RETURN NEW;
        END $$''')
    op.execute('''CREATE TRIGGER pipeline_document_search AFTER UPDATE OF title ON documents
        FOR EACH ROW WHEN (OLD.title IS DISTINCT FROM NEW.title) EXECUTE FUNCTION pipeline_document_search_vector()''')
    op.execute('UPDATE document_chunks SET chunk_text=chunk_text')
    op.execute('CREATE INDEX ix_pipeline_chunk_search ON document_chunks USING gin(search_vector)')


def downgrade():
    if op.get_bind().dialect.name!='postgresql': return
    op.execute('DROP TRIGGER pipeline_document_search ON documents')
    op.execute('DROP FUNCTION pipeline_document_search_vector()')
    op.execute('DROP TRIGGER pipeline_chunk_search ON document_chunks')
    op.execute('DROP FUNCTION pipeline_chunk_search_vector()')
    op.execute('DROP INDEX ix_pipeline_chunk_search')
    op.execute('ALTER TABLE document_chunks DROP COLUMN search_vector')
