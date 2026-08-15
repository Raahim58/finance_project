"""Synchronous Pass 1 evidence flow from discovery through selected indexing."""

from __future__ import annotations

import gzip
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.ingestion.evidence import Candidate, CandidateStatus, EvidenceSource, ParsedEvidence
from app.ingestion.evidence_catalog import SECTOR_DRIVERS, SOURCE_SPECS
from app.models.evidence import DiscoveryCandidate, EvidenceSourceConfig, EvidenceSourceState
from app.models.workstation import (
    DataSource,
    Event,
    EventEntityLink,
    EventSource,
    Instrument,
    InstrumentAlias,
)
from app.providers.evidence.extraction import normalize_url, simhash_distance
from app.services.ingestion_persistence import store_artifact
from app.services.rag_service import ParsedPage, create_document_from_pages

WORD_RE = re.compile(r"[a-z0-9][a-z0-9&./-]*")
STOP_WORDS = frozenset({"a", "an", "and", "at", "by", "for", "from", "in", "of", "on", "the", "to", "with"})
MACRO_TERMS = frozenset(
    {
        "pakistan", "imf", "sbp", "pkr", "inflation", "budget", "tax", "reserves",
        "kibor", "tariff", "current account", "policy rate", "trade deficit",
    }
)
GEOPOLITICAL_TERMS = frozenset(
    {"sanctions", "war", "conflict", "red sea", "shipping", "iran", "gulf", "china", "middle east"}
)
GLOBAL_DRIVER_TERMS = frozenset(
    {
        "federal reserve", "ecb", "interest rate", "global markets", "oil", "lng",
        "natural gas", "coal", "cotton", "steel", "fertilizer", "lithium", "copper",
        "semiconductor", "dram", "nand", "ai chip", "cloud capex", "battery", "freight",
    }
)


@dataclass(frozen=True)
class Score:
    relevance: float
    reasons: tuple[str, ...]
    entity_keys: tuple[str, ...]
    topic: str


@dataclass(frozen=True)
class PipelineResult:
    discovered: int = 0
    evaluated: int = 0
    selected: int = 0
    duplicates: int = 0
    rejected: int = 0
    failed: int = 0


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _tokens(value: str) -> set[str]:
    return {token for token in WORD_RE.findall(value.lower()) if token not in STOP_WORDS}


def _jaccard(left: set[str], right: set[str]) -> float:
    return len(left & right) / len(left | right) if left and right else 0.0


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, default=str)


def _transition(row: DiscoveryCandidate, target: CandidateStatus) -> None:
    from app.ingestion.evidence import validate_candidate_transition

    row.status = validate_candidate_transition(row.status, target).value


def ensure_source_config(db: Session, source_key: str) -> tuple[DataSource, EvidenceSourceConfig, EvidenceSourceState]:
    spec = next((item for item in SOURCE_SPECS if item.key == source_key), None)
    if spec is None:
        raise KeyError(f"No source specification for {source_key!r}")
    data_source = db.scalar(select(DataSource).where(DataSource.name == spec.name))
    if data_source is None:
        data_source = DataSource(
            name=spec.name,
            source_type="evidence",
            base_url=spec.base_url,
            priority={"official": 10, "reporting": 20, "specialist": 25}.get(spec.tier, 50),
            freshness_sla_minutes=max(1, spec.poll_seconds // 60 * 3),
            enabled=spec.enabled,
            use_notes="Phase 3 Global Evidence; exact numerical facts remain in structured tables.",
        )
        db.add(data_source)
        db.flush()
    config = db.scalar(select(EvidenceSourceConfig).where(EvidenceSourceConfig.source_key == spec.key))
    if config is None:
        config = EvidenceSourceConfig(
            data_source_id=data_source.id,
            source_key=spec.key,
            source_tier=spec.tier,
            roles_json=_json(spec.roles),
            categories_json=_json(spec.categories),
            discovery_methods_json=_json((spec.discovery_method,)),
            fetch_methods_json='["http"]',
            languages_json='["en"]',
            poll_interval_seconds=spec.poll_seconds,
            historical_days=spec.historical_days,
            config_version="evidence-v1-pass1",
        )
        db.add(config)
        db.flush()
    state = db.scalar(select(EvidenceSourceState).where(EvidenceSourceState.source_config_id == config.id))
    if state is None:
        state = EvidenceSourceState(source_config_id=config.id)
        db.add(state)
        db.flush()
    return data_source, config, state


def persist_candidate(db: Session, config: EvidenceSourceConfig, candidate: Candidate) -> tuple[DiscoveryCandidate, bool]:
    canonical = normalize_url(candidate.canonical_url or candidate.observed_url)
    url_hash = _hash(canonical)
    filters = [DiscoveryCandidate.canonical_url_hash == url_hash]
    if candidate.external_id:
        filters.append(
            (DiscoveryCandidate.source_config_id == config.id)
            & (DiscoveryCandidate.external_id == candidate.external_id)
        )
    row = db.scalar(select(DiscoveryCandidate).where(or_(*filters)))
    if row is not None:
        row.last_seen_at = candidate.discovered_at
        return row, False
    row = DiscoveryCandidate(
        source_config_id=config.id,
        external_id=candidate.external_id,
        observed_url=candidate.observed_url,
        canonical_url=canonical,
        canonical_url_hash=url_hash,
        headline=candidate.headline[:500],
        normalized_headline_hash=_hash(" ".join(sorted(_tokens(candidate.headline)))),
        publisher=candidate.publisher[:160],
        published_at=candidate.published_at,
        discovered_at=candidate.discovered_at,
        last_seen_at=candidate.discovered_at,
        discovery_method=candidate.discovery_method,
        discovery_query=str(candidate.metadata.get("query") or "")[:255] or None,
        topic=candidate.topic,
        language=candidate.language,
        metadata_json=_json(candidate.metadata),
        configuration_version=config.config_version,
    )
    db.add(row)
    db.flush()
    _transition(row, CandidateStatus.FETCH_READY)
    return row, True


def score_evidence(db: Session, parsed: ParsedEvidence, candidate: Candidate) -> Score:
    """Score substantive matches; source tier and recency never qualify a story alone."""

    text = f"{parsed.title}\n{parsed.body}".lower()
    reasons: list[str] = []
    entities = set(parsed.entity_keys)
    relevance = 0.0
    if candidate.source_key == "psx_announcements":
        relevance = 1.0
        reasons.append("official_psx_announcement")
        entities.update(str(value) for value in (candidate.metadata.get("symbol"),) if value)
    instruments = db.scalars(select(Instrument)).all()
    aliases = db.execute(select(InstrumentAlias.alias, Instrument.symbol).join(Instrument, Instrument.id == InstrumentAlias.instrument_id)).all()
    names = [(item.symbol, item.name) for item in instruments] + [(symbol, alias) for alias, symbol in aliases]
    for symbol, name in names:
        patterns = (symbol, name)
        if any(re.search(rf"(?<![a-z0-9]){re.escape(value.lower())}(?![a-z0-9])", text) for value in patterns if len(value) >= 2):
            entities.add(symbol)
            relevance += 0.65
            reasons.append(f"instrument:{symbol}")
    matched_macro = sorted(term for term in MACRO_TERMS if term in text)
    if matched_macro:
        relevance += min(0.75, 0.18 * len(matched_macro))
        reasons.append("macro:" + ",".join(matched_macro[:4]))
    matched_geo = sorted(term for term in GEOPOLITICAL_TERMS if term in text)
    if matched_geo:
        relevance += min(0.55, 0.14 * len(matched_geo))
        reasons.append("geopolitics:" + ",".join(matched_geo[:4]))
    matched_global = sorted(term for term in GLOBAL_DRIVER_TERMS if term in text)
    if matched_global:
        relevance += min(0.55, 0.14 * len(matched_global))
        reasons.append("global_driver:" + ",".join(matched_global[:4]))
    for instrument in instruments:
        drivers = SECTOR_DRIVERS.get((instrument.sector or "").lower(), ())
        hits = [driver for driver in drivers if driver in text]
        if hits:
            relevance += min(0.35, 0.12 * len(hits))
            reasons.append(f"sector_driver:{instrument.sector}:{','.join(hits[:3])}")
            break
    topic = candidate.topic or ("pakistan_macro" if matched_macro else "geopolitics" if matched_geo else "general")
    return Score(min(1.0, relevance), tuple(dict.fromkeys(reasons)), tuple(sorted(entities)), topic)


def score_candidate_metadata(db: Session, candidate: Candidate) -> Score:
    """Cheap pre-fetch gate based only on discovery metadata."""

    summary = str(candidate.metadata.get("summary") or "")
    body = f"{candidate.headline}\n{summary}".strip()
    preview = ParsedEvidence(
        canonical_url=candidate.canonical_url or candidate.observed_url,
        title=candidate.headline,
        body=body,
        published_at=candidate.published_at,
        source_key=candidate.source_key,
        body_sha256=_hash(body),
        parser_method="discovery_metadata",
        extraction_quality=0.0,
        entity_keys=(str(candidate.metadata["symbol"]),) if candidate.metadata.get("symbol") else (),
    )
    return score_evidence(db, preview, candidate)


def _find_duplicate(db: Session, row: DiscoveryCandidate, parsed: ParsedEvidence) -> DiscoveryCandidate | None:
    exact = db.scalar(
        select(DiscoveryCandidate).where(
            DiscoveryCandidate.id != row.id,
            DiscoveryCandidate.body_sha256 == parsed.body_sha256,
        )
    )
    if exact:
        return exact
    if not parsed.simhash:
        return None
    cutoff = (parsed.published_at or datetime.now(UTC)) - timedelta(days=3)
    candidates = db.scalars(
        select(DiscoveryCandidate).where(
            DiscoveryCandidate.id != row.id,
            DiscoveryCandidate.simhash.is_not(None),
            DiscoveryCandidate.topic == row.topic,
            or_(DiscoveryCandidate.published_at.is_(None), DiscoveryCandidate.published_at >= cutoff),
        ).limit(100)
    ).all()
    return next((item for item in candidates if simhash_distance(parsed.simhash, item.simhash) <= 3), None)


def _cluster(db: Session, row: DiscoveryCandidate, parsed: ParsedEvidence, score: Score) -> Event:
    occurred_at = parsed.published_at or row.published_at or row.discovered_at
    cutoff = occurred_at - timedelta(days=3)
    events = db.scalars(
        select(Event).where(Event.topic == score.topic, Event.occurred_at >= cutoff).limit(100)
    ).all()
    title_tokens = _tokens(parsed.title)
    entity_set = set(score.entity_keys)
    for event in events:
        details = json.loads(event.details_json or "{}")
        prior_entities = set(details.get("entity_keys", []))
        same_entity = bool(entity_set and prior_entities and entity_set & prior_entities)
        if _jaccard(title_tokens, _tokens(event.title)) >= 0.42 or (
            same_entity and _jaccard(title_tokens, _tokens(event.title)) >= 0.22
        ):
            event.event_time_end = max(filter(None, (event.event_time_end, occurred_at)))
            return event
    bucket = occurred_at.astimezone(UTC).strftime("%Y-%m-%d")
    signature = " ".join(sorted(title_tokens))
    event = Event(
        event_type="evidence_story",
        title=parsed.title[:255],
        occurred_at=occurred_at,
        event_time_end=occurred_at,
        cluster_key=_hash(f"{score.topic}|{bucket}|{signature}"),
        topic=score.topic,
        geography="PK" if "pakistan" in parsed.body.lower() or score.topic.startswith("pakistan") else "global",
        confidence=Decimal("0.850000"),
        details_json=_json({"entity_keys": score.entity_keys, "number_fingerprints": parsed.important_number_fingerprints}),
    )
    db.add(event)
    db.flush()
    for entity in score.entity_keys:
        db.add(EventEntityLink(event_id=event.id, entity_type="instrument", entity_key=entity, link_method="exact_alias", confidence=Decimal("1.000000")))
    return event


def _evidence_role(config: EvidenceSourceConfig) -> str:
    roles = json.loads(config.roles_json or "[]")
    if "primary" in roles:
        return "primary"
    if "reporting" in roles:
        return "reporting"
    return "context"


def _select_and_index(
    db: Session,
    data_source: DataSource,
    config: EvidenceSourceConfig,
    row: DiscoveryCandidate,
    event: Event,
    candidate: Candidate,
    parsed: ParsedEvidence,
    raw_content: bytes,
    content_type: str,
) -> bool:
    role = _evidence_role(config)
    occupied = db.scalar(
        select(EventSource).where(
            EventSource.event_id == event.id,
            EventSource.evidence_role == role,
            EventSource.selection_status == "selected",
        )
    )
    event_source = EventSource(
        event_id=event.id,
        candidate_id=row.id,
        source_url=parsed.canonical_url,
        source_name=candidate.publisher,
        published_at=parsed.published_at,
        evidence_role=role,
        selection_status="reference" if occupied else "selected",
        relevance_score=row.relevance_score,
        novelty_score=row.novelty_score,
        quality_score=row.quality_score,
        selection_reasons_json=_json(["role_slot_occupied"] if occupied else [f"selected_{role}_slot"]),
    )
    db.add(event_source)
    db.flush()
    if occupied:
        _transition(row, CandidateStatus.REJECTED)
        return False
    compressed = gzip.compress(raw_content, compresslevel=6, mtime=0)
    artifact = store_artifact(
        db,
        data_source,
        compressed,
        url=parsed.canonical_url,
        method="GET",
        parser_version=parsed.parser_method,
        content_type=f"application/gzip; original={content_type[:80]}",
        effective_at=parsed.published_at,
    )
    symbol = next((key for key in parsed.entity_keys if len(key) <= 30), None)
    document = create_document_from_pages(
        db,
        [ParsedPage(1, parsed.body)],
        title=parsed.title,
        document_type="selected_evidence",
        symbol=symbol,
        source_name=candidate.publisher,
        source_url=parsed.canonical_url,
        published_date=parsed.published_at.date() if parsed.published_at else None,
        visibility="public",
        artifact_id=artifact.id,
        commit=False,
    )
    event_source.artifact_id = artifact.id
    event_source.document_id = document.id
    row.artifact_id = artifact.id
    _transition(row, CandidateStatus.SELECTED)
    return True


def run_source_once(db: Session, evidence_source: EvidenceSource, *, limit: int = 50) -> PipelineResult:
    """Run one source transactionally; Pass 2 will invoke equivalent stages via queues."""

    data_source, config, state = ensure_source_config(db, evidence_source.key)
    state.last_attempted_at = datetime.now(UTC)
    cursor = json.loads(state.cursor_json or "{}")
    try:
        batch = evidence_source.discover_since(cursor, limit)
    except Exception as exc:
        state.consecutive_failures += 1
        state.last_error_class = type(exc).__name__
        state.last_error_message = str(exc)[:2000]
        state.diagnostics_json = _json({"stage": "discovery", "failed": 1})
        db.commit()
        return PipelineResult(failed=1)
    result = PipelineResult(discovered=len(batch.candidates))
    counts = result.__dict__.copy()
    for candidate in batch.candidates:
        row, created = persist_candidate(db, config, candidate)
        if not created:
            continue
        try:
            cheap_score = score_candidate_metadata(db, candidate)
            if cheap_score.relevance < 0.18:
                row.relevance_score = Decimal(f"{cheap_score.relevance:.6f}")
                row.scoring_reasons_json = _json(cheap_score.reasons or ("no_substantive_metadata_match",))
                _transition(row, CandidateStatus.REJECTED)
                counts["rejected"] += 1
                continue
            _transition(row, CandidateStatus.EVALUATING)
            raw = evidence_source.fetch(candidate)
            parsed = evidence_source.normalize(raw)
            canonical_hash = _hash(parsed.canonical_url)
            canonical_match = db.scalar(
                select(DiscoveryCandidate).where(
                    DiscoveryCandidate.id != row.id,
                    DiscoveryCandidate.canonical_url_hash == canonical_hash,
                )
            )
            if canonical_match:
                row.event_id = canonical_match.event_id
                row.novelty_score = Decimal("0.000000")
                row.scoring_reasons_json = '["canonical_url_duplicate"]'
                _transition(row, CandidateStatus.DUPLICATE)
                counts["evaluated"] += 1
                counts["duplicates"] += 1
                continue
            row.canonical_url = parsed.canonical_url
            row.canonical_url_hash = canonical_hash
            row.body_sha256 = parsed.body_sha256
            row.simhash = parsed.simhash
            row.parser_version = parsed.parser_method
            score = score_evidence(db, parsed, candidate)
            row.topic = score.topic
            row.relevance_score = Decimal(f"{score.relevance:.6f}")
            row.quality_score = Decimal(f"{parsed.extraction_quality:.6f}")
            row.scoring_reasons_json = _json(score.reasons)
            counts["evaluated"] += 1
            if score.relevance < 0.30:
                _transition(row, CandidateStatus.REJECTED)
                counts["rejected"] += 1
                continue
            duplicate = _find_duplicate(db, row, parsed)
            if duplicate:
                row.novelty_score = Decimal("0.000000")
                row.event_id = duplicate.event_id
                _transition(row, CandidateStatus.DUPLICATE)
                counts["duplicates"] += 1
                continue
            row.novelty_score = Decimal("1.000000")
            event = _cluster(db, row, parsed, score)
            row.event_id = event.id
            _transition(row, CandidateStatus.CLUSTERED)
            if _select_and_index(db, data_source, config, row, event, candidate, parsed, raw.content, raw.content_type):
                counts["selected"] += 1
            else:
                counts["rejected"] += 1
        except Exception as exc:
            if row.status in {
                CandidateStatus.EVALUATING.value,
                CandidateStatus.CLUSTERED.value,
            }:
                _transition(row, CandidateStatus.FAILED)
            row.last_error_class = type(exc).__name__
            row.last_error_message = str(exc)[:2000]
            counts["failed"] += 1
    state.cursor_json = _json(batch.next_cursor)
    state.last_success_at = datetime.now(UTC)
    state.consecutive_failures = 0
    state.diagnostics_json = _json(counts)
    db.commit()
    return PipelineResult(**counts)
