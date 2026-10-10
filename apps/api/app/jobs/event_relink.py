"""Detach news events from companies their evidence never names (re-attribute to market level).

A document-level company link used to attribute every sentence to that company. This applies the
literal in-quote rule to stored statements; no model calls. Dry run unless --apply.
    python -m app.jobs.event_relink [--apply]
"""
import argparse
from collections import defaultdict
from sqlalchemy import delete, select
from app.db.session import SessionLocal
from app.models.document import Document
from app.models.pipeline import EvidenceStatement
from app.models.pipeline import EventDocumentLink
from app.models.workstation import Event, EventEntityLink, NormalizedEvent, NormalizedEventSubject
from app.services.pipeline.events import refresh_record
from app.services.pipeline.statements import names_in, subject_names


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    apply = parser.parse_args().apply
    with SessionLocal() as db:
        rows = list(db.scalars(select(EvidenceStatement).join(Document, Document.id == EvidenceStatement.document_id)
            .where(EvidenceStatement.subject_type == 'instrument', Document.document_type == 'news')))
        names = subject_names(db, {r.subject_key for r in rows})
        bad = [r for r in rows if not names_in(names[r.subject_key], r.text)]
        events = defaultdict(set)
        for link in db.scalars(select(EventDocumentLink).where(EventDocumentLink.statement_id.in_([r.id for r in bad]))):
            events[link.event_id].add(link.statement_id)
        print({'statements': len(rows), 'misattributed': len(bad), 'events': len(events)})
        if not apply: return
        for statement in bad:
            symbol = statement.subject_key
            statement.subject_type, statement.subject_key = 'market', 'market'
            raw = db.scalar(select(Event.id).where(Event.cluster_key == 'pipeline-statement:' + statement.id))
            if raw: db.execute(delete(EventEntityLink).where(EventEntityLink.event_id == raw, EventEntityLink.entity_key == symbol))
        db.flush()
        for event_id in events:
            event = db.get(NormalizedEvent, event_id)
            if event is None: continue
            kept = {s.subject_key for s in db.scalars(select(EvidenceStatement).join(EventDocumentLink, EventDocumentLink.statement_id == EvidenceStatement.id)
                .where(EventDocumentLink.event_id == event_id))}
            for subject in db.scalars(select(NormalizedEventSubject).where(NormalizedEventSubject.normalized_event_id == event_id)):
                if subject.subject_type == 'instrument' and subject.subject_key not in kept: db.delete(subject)
            if 'market' in kept and db.scalar(select(NormalizedEventSubject.normalized_event_id).where(NormalizedEventSubject.normalized_event_id == event_id,
                    NormalizedEventSubject.subject_key == 'market')) is None:
                db.add(NormalizedEventSubject(normalized_event_id=event_id, subject_type='market', subject_key='market', link_method='classified_entity', confidence=0.5, is_direct=True))
            db.flush(); refresh_record(db, event)
        db.commit()
        print('applied')


if __name__ == '__main__':
    main()
