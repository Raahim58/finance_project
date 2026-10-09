"""Question-time reads of saved event records: SQL filters, then a stated rank.

Rows use the same shape as research_intelligence_service.event_views so every
company, portfolio and Assistant consumer reads them without a second path.
Evidence is the stored original spans; full documents stay behind citations.
"""
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from sqlalchemy import func, select
from app.domain.event_intelligence import event_freshness
from app.domain.research_relevance import detect_factors
from app.models.workstation import NormalizedEvent, NormalizedEventEvidence, NormalizedEventSubject
from app.services.pipeline.events import VERSION

MATERIALITY_WEIGHT = {'high': Decimal('1'), 'medium': Decimal('0.6'), 'low': Decimal('0.2')}
RANK_BASIS = 'freshness 0.45 + materiality 0.35 + confidence 0.20; freshness recomputed at read time'


def today():
    """Day-granular read time keeps ranks and cached portfolio snapshots stable within a day."""
    return datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)


def rank_score(row, *, now=None):
    now = now or today()
    occurred = row['occurred_at']
    occurred = datetime.fromisoformat(occurred) if isinstance(occurred, str) else occurred
    freshness, _ = event_freshness(occurred, now=now)
    confidence = Decimal(str(row.get('confidence') or 0))
    return (Decimal('0.45')*freshness + Decimal('0.35')*MATERIALITY_WEIGHT.get(row.get('materiality'), Decimal('0.2'))
        + Decimal('0.20')*confidence).quantize(Decimal('0.000001'))


def event_records(db, *, symbols=None, event_types=None, start=None, end=None, min_materiality=('medium', 'high'),
                  window_days=None, offset=0, limit=10, candidate_limit=500, now=None):
    now = now or today()
    query = select(NormalizedEvent).where(NormalizedEvent.detection_version==VERSION,
        NormalizedEvent.classification_status=='classified', NormalizedEvent.occurred_at<=now+timedelta(days=366))
    if min_materiality: query = query.where(NormalizedEvent.materiality.in_(min_materiality))
    if symbols:
        query = query.where(NormalizedEvent.id.in_(select(NormalizedEventSubject.normalized_event_id).where(
            NormalizedEventSubject.subject_type=='instrument',
            func.upper(NormalizedEventSubject.subject_key).in_([s.upper() for s in symbols]))))
    if event_types: query = query.where(NormalizedEvent.event_type.in_(list(event_types)))
    if start: query = query.where(NormalizedEvent.occurred_at>=datetime.combine(start, datetime.min.time(), UTC))
    elif window_days: query = query.where(NormalizedEvent.occurred_at>=now-timedelta(days=window_days))
    if end: query = query.where(NormalizedEvent.occurred_at<datetime.combine(end+timedelta(days=1), datetime.min.time(), UTC))
    events = list(db.scalars(query.order_by(NormalizedEvent.occurred_at.desc(), NormalizedEvent.id).limit(candidate_limit)))
    if not events: return []
    ids = [e.id for e in events]
    subjects, raws = {}, {}
    for row in db.scalars(select(NormalizedEventSubject).where(NormalizedEventSubject.normalized_event_id.in_(ids))):
        subjects.setdefault(row.normalized_event_id, []).append(row)
    for event_id, raw_id in db.execute(select(NormalizedEventEvidence.normalized_event_id, NormalizedEventEvidence.raw_event_id)
            .where(NormalizedEventEvidence.normalized_event_id.in_(ids))):
        raws.setdefault(event_id, []).append(raw_id)
    rows = [record_row(e, subjects.get(e.id, []), raws.get(e.id, []), now=now) for e in events]
    for row in rows: row['rank_score'] = rank_score(row, now=now)
    rows.sort(key=lambda r: (-r['rank_score'], r['event_key']))
    return rows[offset:offset+limit]


def record_row(event, subjects, raw_ids, *, now):
    details = json.loads(event.details_json or '{}')
    spans = details.get('evidence_spans', [])
    freshness_score, freshness_status = event_freshness(event.occurred_at, now=now)
    evidence = [{'id': 'statement:'+s['statement_id'], 'raw_event_id': s.get('raw_event_id'), 'document_id': s['document_id'],
        'title': s.get('title'), 'source_name': s.get('source_name'), 'source_url': s.get('source_url') or '',
        'published_at': s.get('published_date'),
        'page_number': s.get('page_number'), 'text': s['quote']} for s in spans]
    return {'id': 'event:'+event.id, 'event_key': 'event:'+event.id, 'normalized_event_id': event.id,
        'raw_event_ids': sorted(raw_ids), 'record': 'classified_event', 'title': event.title,
        'occurred_at': event.occurred_at, 'date_basis': details.get('date_basis'),
        'event_time_end': event.event_time_end, 'geography': event.geography, 'magnitude': None, 'magnitude_unit': None,
        'details': details, 'event_type': event.event_type, 'classification_status': event.classification_status,
        'source_document_type': None, 'statement_kind': details.get('kind'), 'lifecycle': details.get('lifecycle'),
        'lifecycle_history': details.get('lifecycle_history', []), 'reporting_period': details.get('reporting_period'),
        'sectors': details.get('sectors', []), 'topics': details.get('topics', []), 'sentiment': details.get('sentiment'),
        'factor': event.factor, 'factors': detect_factors(event.title+' '+' '.join(s['quote'] for s in spans)),
        'materiality': event.materiality, 'confidence': event.confidence,
        'freshness_status': freshness_status, 'freshness_score': freshness_score,
        'detection_version': event.detection_version, 'source_count': details.get('source_count', len(spans)),
        'subjects': [{'subject_type': s.subject_type, 'subject_key': s.subject_key.upper(), 'link_method': s.link_method,
            'confidence': s.confidence, 'is_direct': s.is_direct}
            for s in sorted(subjects, key=lambda s: s.subject_key) if s.subject_type == 'instrument'],
        'evidence': evidence, 'impact': {'status': 'not_calculated', 'direction': None, 'expected_return': None}}

