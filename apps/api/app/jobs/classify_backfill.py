"""Queue event classification for documents already ingested.

Unchanged documents are skipped: a document is done once a classification
exists for its current content hash and the target classifier version (model
output also satisfies a rules target). Runs are historical-mode stage runs, so
live news keeps priority, and the stage-run input hash includes the content
hash and classifier version so re-running this job never duplicates work.

  python -m app.jobs.classify_backfill --limit 500
  python -m app.jobs.classify_backfill --since 2026-01-01 --document-type news --dry-run
"""
import argparse
import json
from datetime import date
from sqlalchemy import exists, select
from app.core.config import settings
from app.db.session import SessionLocal
from app.models.document import Document
from app.models.pipeline import DocumentClassification, DocumentSection
from app.services.pipeline.classification import MODEL_VERSION, RULES_VERSION
from app.services.pipeline.runs import enqueue


def pending(db, *, target, since=None, document_types=None, limit=500):
    satisfied = [MODEL_VERSION] if target == MODEL_VERSION else [MODEL_VERSION, RULES_VERSION]
    done = exists().where(DocumentClassification.document_id==Document.id,
        DocumentClassification.content_hash==Document.content_hash,
        DocumentClassification.classifier_version.in_(satisfied))
    query = select(Document).where(Document.visibility=='public', Document.owner_user_id.is_(None),
        Document.portfolio_id.is_(None), Document.status.not_in(('revoked', 'superseded', 'failed')), ~done)
    if since: query = query.where(Document.published_date>=since)
    if document_types: query = query.where(Document.document_type.in_(document_types))
    return list(db.scalars(query.order_by(Document.published_date.desc().nulls_last(), Document.id).limit(limit)))


def enqueue_documents(db, documents, *, target):
    queued = {'classify': 0, 'sections': 0}
    for document in documents:
        has_sections = db.scalar(select(exists().where(DocumentSection.document_id==document.id)))
        # Unparsed documents run the whole chain: sections -> link -> classify -> events.
        stage = 'classify' if has_sections else 'sections'
        payload = {'document_id': document.id, 'content_hash': document.content_hash, 'classifier': target}
        enqueue(db, stage, 'document:'+document.id, payload, mode='historical')
        queued[stage] += 1
    return queued


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--since', type=date.fromisoformat)
    parser.add_argument('--document-type', action='append', dest='document_types')
    parser.add_argument('--limit', type=int, default=500)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    target = MODEL_VERSION if settings.pipeline_classification_model_enabled else RULES_VERSION
    with SessionLocal() as db:
        documents = pending(db, target=target, since=args.since, document_types=args.document_types, limit=max(1, args.limit))
        if args.dry_run:
            print(json.dumps({'target': target, 'pending': len(documents)}));return
        queued = enqueue_documents(db, documents, target=target)
        db.commit()
        print(json.dumps({'target': target, 'queued': queued}))


if __name__ == '__main__':
    main()
