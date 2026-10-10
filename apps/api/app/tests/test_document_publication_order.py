from datetime import UTC, date, datetime
from app.db.session import SessionLocal
from app.models.document import Document
from app.models.user import User
from app.services.rag_service import list_documents
import pytest

pytestmark = pytest.mark.usefixtures("database")


def test_publication_order_precedes_limit_and_retains_ownership():
    with SessionLocal() as db:
        owner=User(email='publication-owner@example.test',password_hash='fixture')
        other=User(email='publication-other@example.test',password_hash='fixture')
        db.add_all([owner,other]);db.flush()
        def document(title,published,created,visibility='public',user_id=None):
            return Document(title=title,published_date=published,created_at=created,visibility=visibility,
                owner_user_id=user_id,document_type='annual_report',symbol='FIXTURE',
                source_name='Fixture source',content_hash=title,status='parsed',data_status='observed')
        db.add_all([
            document('Recently added historical report',date(2018,1,1),datetime(2026,10,8,tzinfo=UTC)),
            document('Current published report',date(2026,10,7),datetime(2026,10,7,tzinfo=UTC)),
            document('Other private report',date(2026,10,8),datetime(2026,10,8,tzinfo=UTC),'private',other.id),
        ]);db.commit()
        assert list_documents(db,owner,limit=1,order='published')[0].title=='Current published report'
        assert list_documents(db,owner,limit=1,order='added')[0].title=='Recently added historical report'
