"""Idempotent repair of stored news events against the current attribution and typing rules.

No model calls, no acquisition; each pass only touches rows that still disagree with the rules, so a
second run changes nothing. The pipeline scheduler runs it hourly; run by hand to see counts first:
    python -m app.jobs.event_maintenance [--days 30] [--apply]

1. relink  - a statement that never names its company becomes market-level
2. retype  - market-level statements take market types; company-only types on them are dropped
3. merge   - one news article is one event per subject set (type = most frequent statement type)
4. rescore - recompute title/materiality/subjects for every touched event
"""
import argparse
from collections import defaultdict
from datetime import date, timedelta
from sqlalchemy import delete, select
from app.db.session import SessionLocal
from app.models.document import Document
from app.models.pipeline import EventDocumentLink, EvidenceStatement
from app.models.workstation import Event, EventEntityLink, NormalizedEvent, NormalizedEventEvidence, NormalizedEventSubject
from app.services.pipeline.classification import COMPANY_ONLY_TYPES, market_event_type
from app.services.pipeline.events import VERSION, dominant_type, refresh_record
from app.services.pipeline.statements import names_in, subject_names


def news_statements(db, since):
    return select(EvidenceStatement).join(Document, Document.id == EvidenceStatement.document_id).where(
        Document.document_type == 'news', Document.published_date >= since, EvidenceStatement.validation_status == 'validated')


def relink(db, since, apply):
    rows = list(db.scalars(news_statements(db, since).where(EvidenceStatement.subject_type == 'instrument')))
    names = subject_names(db, {r.subject_key for r in rows})
    bad = [r for r in rows if not names_in(names[r.subject_key], r.text)]
    if apply:
        for statement in bad:
            symbol = statement.subject_key
            statement.subject_type, statement.subject_key = 'market', 'market'
            raw = db.scalar(select(Event.id).where(Event.cluster_key == 'pipeline-statement:' + statement.id))
            if raw: db.execute(delete(EventEntityLink).where(EventEntityLink.event_id == raw, EventEntityLink.entity_key == symbol))
    return {r.id for r in bad}


def retype(db, since, apply):
    touched = set()
    for statement in db.scalars(news_statements(db, since).where(EvidenceStatement.subject_type == 'market', EvidenceStatement.method == 'rules')):
        new = market_event_type(statement.text)
        if new is None and statement.event_type in COMPANY_ONLY_TYPES: statement.validation_status = 'superseded' if apply else statement.validation_status
        elif new and new != statement.event_type and apply: statement.event_type = new
        else: continue
        touched.add(statement.id)
    return touched


def sync_subjects(db, event_id):
    members = list(db.scalars(select(EvidenceStatement).join(EventDocumentLink, EventDocumentLink.statement_id == EvidenceStatement.id)
        .where(EventDocumentLink.event_id == event_id, EvidenceStatement.validation_status == 'validated')))
    kept = {(s.subject_type, s.subject_key) for s in members}
    have = {(s.subject_type, s.subject_key): s for s in db.scalars(select(NormalizedEventSubject).where(NormalizedEventSubject.normalized_event_id == event_id))}
    for key, row in have.items():
        if key not in kept: db.delete(row)
    for kind, key in kept - set(have):
        db.add(NormalizedEventSubject(normalized_event_id=event_id, subject_type=kind, subject_key=key, link_method='classified_entity', confidence=0.5, is_direct=True))
    return members


def merge(db, since, apply):
    """Fold sibling events of one article and subject set into the earliest one."""
    by_event = defaultdict(set)
    for link, statement in db.execute(select(EventDocumentLink, EvidenceStatement).join(EvidenceStatement, EvidenceStatement.id == EventDocumentLink.statement_id)
            .join(Document, Document.id == EventDocumentLink.document_id)
            .join(NormalizedEvent, NormalizedEvent.id == EventDocumentLink.event_id)
            .where(Document.document_type == 'news', Document.published_date >= since, NormalizedEvent.detection_version == VERSION,
                NormalizedEvent.classification_status == 'classified')):
        by_event[link.event_id].add((link.document_id, statement.subject_key))
    stories = defaultdict(list)
    for event_id, keys in by_event.items():
        documents = {d for d, _ in keys}
        if len(documents) == 1: stories[(next(iter(documents)), frozenset(k for _, k in keys))].append(event_id)
    merged, survivors = 0, set()
    for ids in stories.values():
        if len(ids) < 2: continue
        ids.sort(key=lambda i: db.get(NormalizedEvent, i).created_at)
        keep, *rest = ids
        merged += len(rest); survivors.add(keep)
        if not apply: continue
        for event_id in rest:
            for link in db.scalars(select(EventDocumentLink).where(EventDocumentLink.event_id == event_id)): link.event_id = keep
            for evidence in db.scalars(select(NormalizedEventEvidence).where(NormalizedEventEvidence.normalized_event_id == event_id)): evidence.normalized_event_id = keep
            db.execute(delete(NormalizedEventSubject).where(NormalizedEventSubject.normalized_event_id == event_id))
            db.get(NormalizedEvent, event_id).classification_status = 'superseded'
    return merged, survivors


def run(db, days=30, apply=False):
    since = date.today() - timedelta(days=days)
    relinked = relink(db, since, apply)
    if apply: db.flush()
    retyped = retype(db, since, apply)
    if apply: db.flush()
    merged, survivors = merge(db, since, apply)
    if not apply: return {'misattributed': len(relinked), 'retyped_or_dropped': len(retyped), 'events_to_merge': merged}
    affected = set(db.scalars(select(EventDocumentLink.event_id).where(EventDocumentLink.statement_id.in_(relinked | retyped)))) | survivors
    for event_id in affected:
        event = db.get(NormalizedEvent, event_id)
        if event is None or event.classification_status != 'classified': continue
        members = sync_subjects(db, event_id)
        if members: event.event_type = dominant_type([m.event_type for m in sorted(members, key=lambda m: m.id) if m.event_type])
        db.flush(); refresh_record(db, event)
    db.commit()
    return {'misattributed': len(relinked), 'retyped_or_dropped': len(retyped), 'events_merged': merged, 'events_refreshed': len(affected)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--days', type=int, default=30)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    with SessionLocal() as db:
        print(run(db, args.days, args.apply))


if __name__ == '__main__':
    main()
