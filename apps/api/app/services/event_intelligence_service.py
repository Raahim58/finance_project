"""Persistence and query services for deterministic normalized events."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from functools import lru_cache
from urllib.parse import urlparse

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.event_intelligence import (
    DETECTION_VERSION,
    EVENT_RULES,
    MATERIALITY_ORDER,
    classify_event,
    cluster_identity,
    detect_magnitude,
    event_confidence,
    event_freshness,
    event_materiality,
    title_similarity,
)
from app.models.document import Document, DocumentChunk
from app.models.workstation import (
    Event,
    EventEntityLink,
    EventSource,
    Instrument,
    NormalizedEvent,
    NormalizedEventEvidence,
    NormalizedEventSubject,
)
from app.services.portfolio_service import get_portfolio_summary
from app.services.rag_service import cosine_similarity, embed_texts


PROTOTYPES = {
    event_type: f"{event_type.replace('_', ' ')} event: {'; '.join(signals[:4])}"
    for event_type, _factor, signals in EVENT_RULES
}
PRIMARY_SOURCE_TERMS = (
    "pakistan stock exchange", "state bank of pakistan", "securities and exchange commission",
    "government of pakistan", "pakistan bureau of statistics", "issuer",
)


@lru_cache(maxsize=1)
def _prototype_vectors() -> tuple[tuple[str, list[float]], ...]:
    labels = tuple(PROTOTYPES)
    vectors = embed_texts([PROTOTYPES[label] for label in labels])
    return tuple(zip(labels, vectors, strict=True))


def _prototype_match(text: str) -> tuple[str | None, float]:
    vector = embed_texts([text[:2000]])[0]
    scores = [(label, cosine_similarity(vector, prototype)) for label, prototype in _prototype_vectors()]
    return max(scores, key=lambda row: row[1]) if scores else (None, 0.0)


def _source_identity(source: EventSource) -> str:
    host = urlparse(source.source_url).hostname
    return (host or source.source_name).casefold().removeprefix("www.")


def _event_text(db: Session, raw_event: Event, sources: list[EventSource]) -> str:
    document_ids = {source.document_id for source in sources if source.document_id}
    chunks = db.scalars(
        select(DocumentChunk.chunk_text)
        .where(DocumentChunk.document_id.in_(document_ids))
        .order_by(DocumentChunk.document_id, DocumentChunk.chunk_index)
        .limit(24)
    ).all() if document_ids else []
    return "\n".join([raw_event.title, *chunks])[:16000]


def _subjects(db: Session, raw_event: Event, detection_factor: str | None) -> list[dict[str, object]]:
    details = json.loads(raw_event.details_json or "{}")
    official_symbol = str(details.get("official_entity_key") or "").upper()
    result: dict[tuple[str, str], dict[str, object]] = {}
    links = db.scalars(
        select(EventEntityLink).where(EventEntityLink.event_id == raw_event.id)
    ).all()
    for link in links:
        if link.entity_type != "instrument":
            continue
        symbol = link.entity_key.upper()
        method = "issuer_metadata" if official_symbol == symbol else link.link_method
        allowed = method == "issuer_metadata" or method in {
            "exact_alias", "stored_company_name", "stored_alias", "stored_ticker",
            "stored_ticker_context", "explicit_ticker",
        }
        if not allowed:
            continue
        result[("instrument", symbol)] = {
            "subject_type": "instrument", "subject_key": symbol, "link_method": method,
            "confidence": Decimal("1.000000") if method == "issuer_metadata" else link.confidence,
            "is_direct": True,
        }
        instrument = db.scalar(select(Instrument).where(func.upper(Instrument.symbol) == symbol))
        if instrument and instrument.sector:
            result[("sector", instrument.sector)] = {
                "subject_type": "sector", "subject_key": instrument.sector,
                "link_method": "derived_from_direct_instrument", "confidence": Decimal("0.850000"),
                "is_direct": False,
            }
    if detection_factor:
        result[("macro_factor", detection_factor)] = {
            "subject_type": "macro_factor", "subject_key": detection_factor,
            "link_method": "event_taxonomy", "confidence": Decimal("1.000000"),
            "is_direct": False,
        }
    return list(result.values())


def _matching_cluster(
    db: Session,
    raw_event: Event,
    event_type: str,
    subjects: list[dict[str, object]],
) -> NormalizedEvent | None:
    if event_type == "unclassified":
        return None
    cutoff = raw_event.occurred_at - timedelta(days=7)
    ceiling = raw_event.occurred_at + timedelta(days=7)
    subject_keys = {
        str(subject["subject_key"])
        for subject in subjects
        if subject["subject_type"] in {"instrument", "macro_factor"}
    }
    candidates = db.scalars(
        select(NormalizedEvent).where(
            NormalizedEvent.event_type == event_type,
            NormalizedEvent.occurred_at >= cutoff,
            NormalizedEvent.occurred_at <= ceiling,
        ).limit(100)
    ).all()
    for candidate in candidates:
        existing_keys = set(db.scalars(
            select(NormalizedEventSubject.subject_key).where(
                NormalizedEventSubject.normalized_event_id == candidate.id,
                NormalizedEventSubject.subject_type.in_(("instrument", "macro_factor")),
            )
        ))
        if subject_keys and existing_keys and not subject_keys.intersection(existing_keys):
            continue
        if title_similarity(raw_event.title, candidate.title) >= 0.34:
            return candidate
    return None


def normalize_raw_event(
    db: Session,
    raw_event_id: str,
    *,
    commit: bool = True,
    prototype_match: tuple[str | None, float] | None = None,
) -> NormalizedEvent:
    existing = db.scalar(
        select(NormalizedEvent)
        .join(NormalizedEventEvidence, NormalizedEventEvidence.normalized_event_id == NormalizedEvent.id)
        .where(NormalizedEventEvidence.raw_event_id == raw_event_id)
    )
    if existing:
        score, status = event_freshness(existing.occurred_at)
        existing.freshness_score = score
        existing.freshness_status = status
        if commit:
            db.commit()
        return existing

    raw_event = db.get(Event, raw_event_id)
    if raw_event is None:
        raise ValueError("Raw event not found")
    sources = list(db.scalars(select(EventSource).where(EventSource.event_id == raw_event.id)))
    if not sources:
        raise ValueError("Raw event has no retained source evidence")
    raw_details = json.loads(raw_event.details_json or "{}")
    if raw_details.get("data_classification") == "synthetic_demo" or all(
        "demo" in source.source_name.casefold() or source.source_url.casefold().startswith("demo://")
        for source in sources
    ):
        raise ValueError("Synthetic/demo events cannot become observed normalized events")
    text = _event_text(db, raw_event, sources)
    detection = classify_event(raw_event.title)
    if detection.classification_status == "classified":
        detection = replace(detection, magnitude=detect_magnitude(text))
    else:
        detection = classify_event(text)
    subjects = _subjects(db, raw_event, detection.factor)
    direct_subjects = [subject for subject in subjects if subject["is_direct"]]
    source_identities = {_source_identity(source) for source in sources}
    documents = list(db.scalars(
        select(Document).where(Document.id.in_({source.document_id for source in sources if source.document_id}))
    ))
    primary_source = any(
        any(term in source.source_name.casefold() for term in PRIMARY_SOURCE_TERMS)
        for source in sources
    ) or any(document.source_tier == 1 for document in documents)
    prototype_type, prototype_score = prototype_match or _prototype_match(raw_event.title)
    prototype_agreement = prototype_type == detection.event_type and prototype_score >= 0.30
    materiality = event_materiality(detection, text, has_direct_subject=bool(direct_subjects))
    confidence = event_confidence(
        detection,
        primary_source=primary_source,
        has_direct_subject=bool(direct_subjects),
        independent_source_count=len(source_identities),
        prototype_agreement=prototype_agreement,
    )
    freshness_score, freshness_status = event_freshness(raw_event.occurred_at)
    normalized = _matching_cluster(db, raw_event, detection.event_type, subjects)
    if normalized is None:
        identity_subjects = tuple(
            f"{subject['subject_type']}:{subject['subject_key']}" for subject in subjects
        )
        if detection.classification_status == "unclassified":
            identity_subjects = (*identity_subjects, f"raw_event:{raw_event.id}")
        normalized = NormalizedEvent(
            event_type=detection.event_type,
            classification_status=detection.classification_status,
            title=raw_event.title,
            occurred_at=raw_event.occurred_at,
            event_time_end=raw_event.event_time_end or raw_event.occurred_at,
            cluster_key=cluster_identity(detection.event_type, raw_event.occurred_at, identity_subjects, raw_event.title),
            factor=detection.factor,
            geography=raw_event.geography,
            magnitude=detection.magnitude.value if detection.magnitude else None,
            magnitude_unit=detection.magnitude.unit if detection.magnitude else None,
            materiality=materiality,
            confidence=confidence,
            freshness_score=freshness_score,
            freshness_status=freshness_status,
            detection_version=DETECTION_VERSION,
            details_json=json.dumps({
                "matched_signals": detection.matched_signals,
                "magnitude_direction": detection.magnitude.direction if detection.magnitude else None,
                "magnitude_text": detection.magnitude.matched_text if detection.magnitude else None,
                "prototype": {"event_type": prototype_type, "similarity": round(prototype_score, 6), "supporting_only": True},
                "independent_source_count": len(source_identities),
                "impact_interpretation": "not_calculated",
            }, sort_keys=True),
        )
        db.add(normalized)
        db.flush()
    else:
        normalized.event_time_end = max(
            normalized.event_time_end or normalized.occurred_at,
            raw_event.event_time_end or raw_event.occurred_at,
        )
        if MATERIALITY_ORDER[materiality] > MATERIALITY_ORDER[normalized.materiality]:
            normalized.materiality = materiality
        normalized.confidence = max(normalized.confidence, confidence)
        normalized.freshness_score = max(normalized.freshness_score, freshness_score)
        normalized.freshness_status = freshness_status if freshness_score >= normalized.freshness_score else normalized.freshness_status

    evidence_count = db.scalar(
        select(func.count()).select_from(NormalizedEventEvidence).where(
            NormalizedEventEvidence.normalized_event_id == normalized.id
        )
    ) or 0
    existing_source_identities = set(db.scalars(
        select(EventSource.source_url)
        .join(NormalizedEventEvidence, NormalizedEventEvidence.raw_event_id == EventSource.event_id)
        .where(NormalizedEventEvidence.normalized_event_id == normalized.id)
    ))
    evidence_role = "primary" if evidence_count == 0 else (
        "corroborating"
        if any(source.source_url not in existing_source_identities for source in sources)
        else "supporting_duplicate"
    )
    db.add(NormalizedEventEvidence(
        normalized_event_id=normalized.id,
        raw_event_id=raw_event.id,
        evidence_role=evidence_role,
    ))
    db.flush()
    existing_subjects = {
        (row.subject_type, row.subject_key)
        for row in db.scalars(select(NormalizedEventSubject).where(
            NormalizedEventSubject.normalized_event_id == normalized.id
        ))
    }
    for subject in subjects:
        key = (str(subject["subject_type"]), str(subject["subject_key"]))
        if key not in existing_subjects:
            db.add(NormalizedEventSubject(normalized_event_id=normalized.id, **subject))
    cluster_sources = list(db.scalars(
        select(EventSource)
        .join(NormalizedEventEvidence, NormalizedEventEvidence.raw_event_id == EventSource.event_id)
        .where(NormalizedEventEvidence.normalized_event_id == normalized.id)
    ))
    independent_count = len({_source_identity(source) for source in cluster_sources})
    normalized_details = json.loads(normalized.details_json or "{}")
    previous_count = int(normalized_details.get("independent_source_count") or 0)
    if previous_count < 2 <= independent_count:
        normalized.confidence = min(Decimal("0.990000"), normalized.confidence + Decimal("0.080000"))
    normalized_details["independent_source_count"] = independent_count
    normalized.details_json = json.dumps(normalized_details, sort_keys=True)
    if commit:
        db.commit()
    else:
        db.flush()
    return normalized


def normalize_pending_events(db: Session, *, limit: int = 500) -> dict[str, int]:
    linked_ids = select(NormalizedEventEvidence.raw_event_id)
    rows = list(db.execute(
        select(Event.id, Event.title, Event.occurred_at)
        .join(EventSource, EventSource.event_id == Event.id)
        .where(
            Event.event_type.in_(("announcement", "news", "evidence_story")),
            ~Event.id.in_(linked_ids),
            ~func.lower(EventSource.source_name).contains("demo"),
            ~func.lower(EventSource.source_url).like("demo://%"),
        )
        .distinct()
        .order_by(Event.occurred_at.desc())
        .limit(limit)
    ))
    vectors = embed_texts([title[:2000] for _event_id, title, _occurred_at in rows]) if rows else []
    prototypes = _prototype_vectors() if rows else ()
    prototype_matches = [
        max(
            ((label, cosine_similarity(vector, prototype)) for label, prototype in prototypes),
            key=lambda row: row[1],
        )
        for vector in vectors
    ]
    classified = unclassified = 0
    for (event_id, _title, _occurred_at), prototype in zip(rows, prototype_matches, strict=True):
        event = normalize_raw_event(db, event_id, commit=False, prototype_match=prototype)
        classified += int(event.classification_status == "classified")
        unclassified += int(event.classification_status == "unclassified")
    db.commit()
    return {"scanned": len(rows), "classified": classified, "unclassified": unclassified}


def serialize_normalized_event(db: Session, event: NormalizedEvent) -> dict[str, object]:
    subjects = list(db.scalars(select(NormalizedEventSubject).where(
        NormalizedEventSubject.normalized_event_id == event.id
    )))
    raw_events = list(db.scalars(
        select(Event)
        .join(NormalizedEventEvidence, NormalizedEventEvidence.raw_event_id == Event.id)
        .where(NormalizedEventEvidence.normalized_event_id == event.id)
    ))
    raw_ids = [row.id for row in raw_events]
    sources = list(db.scalars(select(EventSource).where(EventSource.event_id.in_(raw_ids)))) if raw_ids else []
    return {
        "id": event.id,
        "event_type": event.event_type,
        "classification_status": event.classification_status,
        "title": event.title,
        "occurred_at": event.occurred_at,
        "event_time_end": event.event_time_end,
        "factor": event.factor,
        "geography": event.geography,
        "magnitude": event.magnitude,
        "magnitude_unit": event.magnitude_unit,
        "materiality": event.materiality,
        "confidence": event.confidence,
        "freshness_score": event.freshness_score,
        "freshness_status": event.freshness_status,
        "detection_version": event.detection_version,
        "details": json.loads(event.details_json),
        "subjects": [{
            "subject_type": row.subject_type, "subject_key": row.subject_key,
            "link_method": row.link_method, "confidence": row.confidence, "is_direct": row.is_direct,
        } for row in subjects],
        "evidence": [{
            "raw_event_id": source.event_id,
            "source_name": source.source_name,
            "source_url": source.source_url,
            "published_at": source.published_at,
            "document_id": source.document_id,
        } for source in sources],
        "impact": {"status": "not_calculated", "direction": None, "expected_return": None},
    }


def list_normalized_events(
    db: Session,
    *, subject_type: str | None = None,
    subject_key: str | None = None,
    event_type: str | None = None,
    materiality: str | None = None,
    include_unclassified: bool = False,
    limit: int = 100,
) -> list[dict[str, object]]:
    statement = select(NormalizedEvent)
    if not include_unclassified:
        statement = statement.where(NormalizedEvent.classification_status == "classified")
    if subject_key or subject_type:
        statement = statement.join(
            NormalizedEventSubject,
            NormalizedEventSubject.normalized_event_id == NormalizedEvent.id,
        )
        if subject_key:
            statement = statement.where(func.upper(NormalizedEventSubject.subject_key) == subject_key.upper())
        if subject_type:
            statement = statement.where(NormalizedEventSubject.subject_type == subject_type)
    if event_type:
        statement = statement.where(NormalizedEvent.event_type == event_type)
    if materiality:
        statement = statement.where(NormalizedEvent.materiality == materiality)
    events = list(db.scalars(statement.order_by(NormalizedEvent.occurred_at.desc()).limit(limit)).unique())
    return [serialize_normalized_event(db, event) for event in events]


def portfolio_event_exposure(db: Session, user, portfolio_id: str, *, limit: int = 100) -> dict[str, object]:
    summary = get_portfolio_summary(db, user, portfolio_id)
    weights = {
        holding.symbol.upper(): float(holding.market_value / summary.total_value)
        if summary.total_value else 0.0
        for holding in summary.holdings
    }
    if not weights:
        return {"portfolio_id": portfolio_id, "events": [], "impact_calculation": "not_available"}
    matched_events = list(db.scalars(
        select(NormalizedEvent)
        .join(
            NormalizedEventSubject,
            NormalizedEventSubject.normalized_event_id == NormalizedEvent.id,
        )
        .where(
            NormalizedEvent.classification_status == "classified",
            NormalizedEventSubject.subject_type == "instrument",
            NormalizedEventSubject.is_direct.is_(True),
            func.upper(NormalizedEventSubject.subject_key).in_(weights),
        )
        .order_by(NormalizedEvent.occurred_at.desc())
        .limit(limit)
    ).unique())
    events = [serialize_normalized_event(db, event) for event in matched_events]
    result = []
    for event in events:
        symbols = sorted({
            str(subject["subject_key"]).upper()
            for subject in event["subjects"]
            if subject["subject_type"] == "instrument" and subject["is_direct"]
        } & weights.keys())
        if symbols:
            result.append({
                "event": event,
                "holdings": [{"symbol": symbol, "current_portfolio_weight": weights[symbol]} for symbol in symbols],
                "affected_portfolio_weight": sum(weights[symbol] for symbol in symbols),
                "impact_direction": None,
                "impact_calculation": "not_implemented_without_verified_sensitivities",
            })
    result.sort(
        key=lambda row: (
            -MATERIALITY_ORDER[str(row["event"]["materiality"])],
            -float(row["affected_portfolio_weight"]),
            -float(row["event"]["freshness_score"]),
        )
    )
    return {"portfolio_id": portfolio_id, "events": result, "impact_calculation": "not_implemented_without_verified_sensitivities"}
