"""Tag only bounded curated batch documents; preserve text and embeddings."""
import json
from sqlalchemy import select
from app.db.session import SessionLocal
from app.models.document import Document,DocumentPage
from app.models.evidence import DiscoveryCandidate
from app.models.workstation import EventSource
from app.ingestion.news_selection import classify_news
from app.services.news_retrieval import tag_document


def main():
    tagged=excluded=0
    with SessionLocal() as db:
        rows=db.execute(select(DiscoveryCandidate,EventSource,Document)
            .join(EventSource,EventSource.candidate_id==DiscoveryCandidate.id)
            .join(Document,Document.id==EventSource.document_id)
            .where(DiscoveryCandidate.metadata_json.contains('curated_news'))
            .order_by(DiscoveryCandidate.discovered_at.desc()).limit(200)).all()
        for candidate,source,document in rows:
            text='\n'.join(db.scalars(select(DocumentPage.text).where(DocumentPage.document_id==document.id)))
            curation=classify_news(document.title,text)
            if not curation['eligible']:
                document.data_status='excluded_irrelevant'
                source.selection_status='excluded'
                source.selection_reasons_json='["curated_material_news_filter"]'
                excluded+=1
            else:
                tag_document(db,document,text);tagged+=1
            print(json.dumps({'document_id':document.id,'title':document.title,
                'outcome':'tagged' if curation['eligible'] else 'excluded',
                'sectors':curation['sectors'],'topics':curation['topics']}),flush=True)
        db.commit()
    print(json.dumps({'tagged':tagged,'excluded':excluded,'embeddings_rebuilt':0}),flush=True)


if __name__=='__main__': main()
