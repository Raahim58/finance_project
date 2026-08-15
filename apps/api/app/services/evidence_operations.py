"""Durable Pass 2 evidence stages used by Celery workers and reconstruction."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.ingestion.evidence import Candidate, CandidateStatus, EvidenceSource, ParsedEvidence, RawContent
from app.models.evidence import (
    DiscoveryCandidate,
    EvidenceRefreshRequest,
    EvidenceSourceConfig,
)
from app.models.workstation import DataSource, EventSource
from app.services.evidence_pipeline import (
    _cluster,
    _evidence_role,
    _find_duplicate,
    _hash,
    _json,
    _transition,
    ensure_source_config,
    persist_candidate,
    score_candidate_metadata,
    score_evidence,
)
from app.services.ingestion_persistence import store_artifact
from app.services.rag_service import ParsedPage, create_document_from_pages, parse_pdf


@dataclass(frozen=True)
class DiscoveryStageResult:
    candidate_ids: tuple[str, ...]
    discovered: int
    new: int


@dataclass(frozen=True)
class FetchStageResult:
    candidate_id: str
    outcome: str
    content_type: str | None = None


@dataclass(frozen=True)
class ParseStageResult:
    candidate_id: str
    outcome: str


class EvidenceSpool:
    """Bounded local/shared-volume spool; paths never originate from source input."""

    def __init__(self, root: str | Path | None = None) -> None:
        base = Path(root or settings.source_artifact_root)
        self.root = base / ".evidence-spool"
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, candidate_id: str, suffix: str) -> Path:
        safe_id = "".join(char for char in candidate_id if char.isalnum() or char in {"-", "_"})
        if not safe_id or safe_id != candidate_id:
            raise ValueError("Invalid candidate spool identifier")
        return self.root / f"{safe_id}.{suffix}"

    @staticmethod
    def _atomic_write(path: Path, content: bytes) -> None:
        temporary = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
        temporary.write_bytes(content)
        temporary.replace(path)

    def write_raw(self, candidate_id: str, content: bytes) -> str:
        path = self._path(candidate_id, "raw")
        self._atomic_write(path, content)
        return str(path)

    def read_raw(self, candidate_id: str) -> bytes:
        return self._path(candidate_id, "raw").read_bytes()

    def write_parsed(self, candidate_id: str, parsed: ParsedEvidence) -> str:
        path = self._path(candidate_id, "parsed.json.gz")
        payload = json.dumps(asdict(parsed), sort_keys=True, default=str).encode()
        self._atomic_write(path, gzip.compress(payload, compresslevel=6, mtime=0))
        return str(path)

    def read_parsed(self, candidate_id: str) -> ParsedEvidence:
        payload = json.loads(gzip.decompress(self._path(candidate_id, "parsed.json.gz").read_bytes()))
        published = datetime.fromisoformat(payload["published_at"]) if payload.get("published_at") else None
        return ParsedEvidence(
            canonical_url=payload["canonical_url"],
            title=payload["title"],
            body=payload["body"],
            published_at=published,
            source_key=payload["source_key"],
            body_sha256=payload["body_sha256"],
            parser_method=payload["parser_method"],
            extraction_quality=float(payload["extraction_quality"]),
            author=payload.get("author"),
            language=payload.get("language"),
            sections=tuple(payload.get("sections", [])),
            entity_keys=tuple(payload.get("entity_keys", [])),
            important_number_fingerprints=tuple(payload.get("important_number_fingerprints", [])),
            simhash=payload.get("simhash"),
            metadata=payload.get("metadata", {}),
        )

    def cleanup(self, candidate_id: str) -> None:
        for suffix in ("raw", "parsed.json.gz"):
            self._path(candidate_id, suffix).unlink(missing_ok=True)

    def prune(self, older_than: datetime) -> int:
        removed = 0
        cutoff = older_than.timestamp()
        for path in self.root.glob("*"):
            if path.is_file() and path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)
                removed += 1
        return removed


def candidate_from_row(row: DiscoveryCandidate, source_key: str) -> Candidate:
    metadata = json.loads(row.metadata_json or "{}")
    metadata.pop("_pipeline", None)
    return Candidate(
        source_key=source_key,
        observed_url=row.observed_url,
        headline=row.headline,
        publisher=row.publisher,
        discovered_at=row.discovered_at,
        discovery_method=row.discovery_method,
        external_id=row.external_id,
        canonical_url=row.canonical_url,
        published_at=row.published_at,
        topic=row.topic,
        language=row.language,
        metadata=metadata,
    )


def _pipeline_metadata(row: DiscoveryCandidate) -> tuple[dict[str, Any], dict[str, Any]]:
    metadata = json.loads(row.metadata_json or "{}")
    pipeline = metadata.setdefault("_pipeline", {})
    return metadata, pipeline


def _record_request_outcome(db: Session, row: DiscoveryCandidate, outcome: str) -> None:
    metadata = json.loads(row.metadata_json or "{}")
    request_id = metadata.get("request_id")
    if not request_id:
        return
    request = db.get(EvidenceRefreshRequest, request_id)
    if request is None:
        return
    if outcome == "selected":
        request.selected_count += 1
    elif outcome == "duplicate":
        request.duplicate_count += 1
    elif outcome == "rejected":
        request.rejected_count += 1


def discover_stage(
    db: Session,
    evidence_source: EvidenceSource,
    *,
    limit: int,
    priority_class: str = "live",
    cursor_override: dict[str, Any] | None = None,
    request_id: str | None = None,
) -> DiscoveryStageResult:
    _, config, state = ensure_source_config(db, evidence_source.key)
    now = datetime.now(UTC)
    state.last_attempted_at = now
    cursor = dict(cursor_override if cursor_override is not None else json.loads(state.cursor_json or "{}"))
    try:
        batch = evidence_source.discover_since(cursor, limit)
        identifiers: list[str] = []
        new_count = 0
        for candidate in batch.candidates:
            metadata = {
                **dict(candidate.metadata),
                "priority_class": priority_class,
                **({"request_id": request_id} if request_id else {}),
            }
            enriched = replace(candidate, metadata=metadata)
            row, created = persist_candidate(db, config, enriched)
            if created:
                identifiers.append(row.id)
                new_count += 1
        if cursor_override is None:
            state.cursor_json = _json(batch.next_cursor)
        state.last_success_at = now
        state.next_poll_at = now + timedelta(seconds=config.poll_interval_seconds)
        state.consecutive_failures = 0
        state.last_error_class = None
        state.last_error_message = None
        state.diagnostics_json = _json(
            {"last_discovered": len(batch.candidates), "last_new": new_count, "circuit_open_until": None}
        )
        if request_id:
            request = db.get(EvidenceRefreshRequest, request_id)
            if request:
                request.discovered_count += new_count
                request.status = "processing" if request.discovered_count else "complete"
                if not request.discovered_count:
                    request.completed_at = now
        db.commit()
        return DiscoveryStageResult(tuple(identifiers), len(batch.candidates), new_count)
    except Exception as exc:
        state.consecutive_failures += 1
        state.last_error_class = type(exc).__name__
        state.last_error_message = str(exc)[:2000]
        circuit_until = None
        if state.consecutive_failures >= settings.evidence_circuit_failure_threshold:
            circuit_until = now + timedelta(seconds=settings.evidence_circuit_open_seconds)
            state.next_poll_at = circuit_until
        state.diagnostics_json = _json(
            {"stage": "discovery", "circuit_open_until": circuit_until.isoformat() if circuit_until else None}
        )
        if request_id:
            request = db.get(EvidenceRefreshRequest, request_id)
            if request:
                request.status = "failed"
                request.error_class = type(exc).__name__
                request.error_message = str(exc)[:2000]
                request.completed_at = now
        db.commit()
        raise


def fetch_stage(
    db: Session,
    evidence_source: EvidenceSource,
    candidate_id: str,
    *,
    spool: EvidenceSpool | None = None,
) -> FetchStageResult:
    spool = spool or EvidenceSpool()
    row = db.get(DiscoveryCandidate, candidate_id)
    if row is None:
        raise ValueError("Evidence candidate not found")
    if row.status == CandidateStatus.FAILED.value:
        _transition(row, CandidateStatus.FETCH_READY)
    if row.status != CandidateStatus.FETCH_READY.value:
        return FetchStageResult(row.id, f"idempotent_{row.status}")
    candidate = candidate_from_row(row, evidence_source.key)
    cheap_score = score_candidate_metadata(db, candidate)
    if cheap_score.relevance < 0.18:
        row.relevance_score = Decimal(f"{cheap_score.relevance:.6f}")
        row.scoring_reasons_json = _json(cheap_score.reasons or ("no_substantive_metadata_match",))
        _transition(row, CandidateStatus.REJECTED)
        row.lease_expires_at = None
        _record_request_outcome(db, row, "rejected")
        db.commit()
        return FetchStageResult(row.id, "rejected")
    _transition(row, CandidateStatus.EVALUATING)
    row.lease_expires_at = datetime.now(UTC) + timedelta(seconds=settings.evidence_stage_lease_seconds)
    db.commit()
    try:
        raw = evidence_source.fetch(candidate)
        raw_path = spool.write_raw(row.id, raw.content)
        row = db.get(DiscoveryCandidate, candidate_id)
        metadata, pipeline = _pipeline_metadata(row)
        pipeline.update(
            {
                "stage": "raw_ready",
                "raw_path": raw_path,
                "content_type": raw.content_type,
                "final_url": raw.final_url,
                "retrieved_at": raw.retrieved_at.isoformat(),
                "headers": {
                    key.lower(): value
                    for key, value in raw.headers.items()
                    if key.lower() in {"etag", "last-modified", "content-length"}
                },
            }
        )
        row.metadata_json = _json(metadata)
        row.lease_expires_at = None
        row.last_error_class = None
        row.last_error_message = None
        db.commit()
        return FetchStageResult(row.id, "raw_ready", raw.content_type)
    except Exception as exc:
        db.rollback()
        row = db.get(DiscoveryCandidate, candidate_id)
        if row and row.status == CandidateStatus.EVALUATING.value:
            _transition(row, CandidateStatus.FAILED)
            row.retry_count += 1
            delay = settings.evidence_retry_backoff_seconds * (2 ** max(0, row.retry_count - 1))
            row.next_attempt_at = datetime.now(UTC) + timedelta(seconds=min(delay, 3600))
            row.lease_expires_at = None
            row.last_error_class = type(exc).__name__
            row.last_error_message = str(exc)[:2000]
            db.commit()
        raise


def _pdf_evidence(raw: RawContent, source_key: str) -> ParsedEvidence:
    pages = parse_pdf(raw.content)
    body = "\n\n".join(page.text for page in pages if page.text.strip())
    if not body:
        body = raw.candidate.headline
    digest = hashlib.sha256(body.encode()).hexdigest()
    return ParsedEvidence(
        canonical_url=raw.candidate.canonical_url or raw.candidate.observed_url,
        title=raw.candidate.headline,
        body=body,
        published_at=raw.candidate.published_at,
        source_key=source_key,
        body_sha256=digest,
        parser_method="pypdf_evidence_v1",
        extraction_quality=min(1.0, 0.4 + len(body.split()) / 1000),
        entity_keys=(str(raw.candidate.metadata["symbol"]),) if raw.candidate.metadata.get("symbol") else (),
        metadata={**dict(raw.candidate.metadata), "page_count": len(pages)},
    )


def parse_stage(
    db: Session,
    evidence_source: EvidenceSource,
    candidate_id: str,
    *,
    pdf: bool = False,
    spool: EvidenceSpool | None = None,
) -> ParseStageResult:
    spool = spool or EvidenceSpool()
    row = db.get(DiscoveryCandidate, candidate_id)
    if row is None:
        raise ValueError("Evidence candidate not found")
    metadata, pipeline = _pipeline_metadata(row)
    if row.status != CandidateStatus.EVALUATING.value or pipeline.get("stage") != "raw_ready":
        return ParseStageResult(row.id, f"idempotent_{row.status}")
    candidate = candidate_from_row(row, evidence_source.key)
    raw = RawContent(
        candidate=candidate,
        content=spool.read_raw(row.id),
        content_type=str(pipeline.get("content_type") or "application/octet-stream"),
        retrieved_at=datetime.fromisoformat(str(pipeline["retrieved_at"])),
        final_url=str(pipeline.get("final_url") or candidate.observed_url),
        headers=pipeline.get("headers", {}),
    )
    try:
        parsed = _pdf_evidence(raw, evidence_source.key) if pdf else evidence_source.normalize(raw)
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
            _record_request_outcome(db, row, "duplicate")
            spool.cleanup(row.id)
            db.commit()
            return ParseStageResult(row.id, "duplicate")
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
        if score.relevance < 0.30:
            _transition(row, CandidateStatus.REJECTED)
            _record_request_outcome(db, row, "rejected")
            spool.cleanup(row.id)
            db.commit()
            return ParseStageResult(row.id, "rejected")
        duplicate = _find_duplicate(db, row, parsed)
        if duplicate:
            row.novelty_score = Decimal("0.000000")
            row.event_id = duplicate.event_id
            _transition(row, CandidateStatus.DUPLICATE)
            _record_request_outcome(db, row, "duplicate")
            spool.cleanup(row.id)
            db.commit()
            return ParseStageResult(row.id, "duplicate")
        row.novelty_score = Decimal("1.000000")
        event = _cluster(db, row, parsed, score)
        row.event_id = event.id
        _transition(row, CandidateStatus.CLUSTERED)
        config = db.get(EvidenceSourceConfig, row.source_config_id)
        role = _evidence_role(config)
        occupied = db.scalar(
            select(EventSource).where(
                EventSource.event_id == event.id,
                EventSource.evidence_role == role,
                EventSource.selection_status.in_(("pending", "selected")),
            )
        )
        event_source = EventSource(
            event_id=event.id,
            candidate_id=row.id,
            source_url=parsed.canonical_url,
            source_name=candidate.publisher,
            published_at=parsed.published_at,
            evidence_role=role,
            selection_status="reference" if occupied else "pending",
            relevance_score=row.relevance_score,
            novelty_score=row.novelty_score,
            quality_score=row.quality_score,
            selection_reasons_json=_json(
                ["role_slot_occupied"] if occupied else [f"reserved_{role}_slot"]
            ),
        )
        db.add(event_source)
        if occupied:
            _transition(row, CandidateStatus.REJECTED)
            _record_request_outcome(db, row, "rejected")
            spool.cleanup(row.id)
            db.commit()
            return ParseStageResult(row.id, "reference")
        pipeline["stage"] = "parsed_ready"
        pipeline["parsed_path"] = spool.write_parsed(row.id, parsed)
        row.metadata_json = _json(metadata)
        row.lease_expires_at = None
        db.commit()
        return ParseStageResult(row.id, "index_ready")
    except Exception as exc:
        db.rollback()
        row = db.get(DiscoveryCandidate, candidate_id)
        if row and row.status == CandidateStatus.EVALUATING.value:
            _transition(row, CandidateStatus.FAILED)
            row.retry_count += 1
            row.next_attempt_at = datetime.now(UTC) + timedelta(
                seconds=min(settings.evidence_retry_backoff_seconds * 2 ** max(0, row.retry_count - 1), 3600)
            )
            row.last_error_class = type(exc).__name__
            row.last_error_message = str(exc)[:2000]
            db.commit()
        raise


def index_stage(db: Session, candidate_id: str, *, spool: EvidenceSpool | None = None) -> ParseStageResult:
    spool = spool or EvidenceSpool()
    row = db.get(DiscoveryCandidate, candidate_id)
    if row is None:
        raise ValueError("Evidence candidate not found")
    event_source = db.scalar(select(EventSource).where(EventSource.candidate_id == row.id))
    if row.status == CandidateStatus.SELECTED.value and event_source and event_source.document_id:
        spool.cleanup(row.id)
        return ParseStageResult(row.id, "idempotent_selected")
    metadata, pipeline = _pipeline_metadata(row)
    if row.status != CandidateStatus.CLUSTERED.value or not event_source or event_source.selection_status != "pending":
        return ParseStageResult(row.id, f"idempotent_{row.status}")
    try:
        parsed = spool.read_parsed(row.id)
        raw_content = spool.read_raw(row.id)
        config = db.get(EvidenceSourceConfig, row.source_config_id)
        data_source = db.get(DataSource, config.data_source_id)
        content_type = str(pipeline.get("content_type") or "application/octet-stream")
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
            source_name=row.publisher,
            source_url=parsed.canonical_url,
            published_date=parsed.published_at.date() if parsed.published_at else None,
            visibility="public",
            artifact_id=artifact.id,
            commit=False,
        )
        event_source.artifact_id = artifact.id
        event_source.document_id = document.id
        event_source.selection_status = "selected"
        event_source.selection_reasons_json = _json([f"selected_{event_source.evidence_role}_slot"])
        row.artifact_id = artifact.id
        _transition(row, CandidateStatus.SELECTED)
        pipeline["stage"] = "complete"
        row.metadata_json = _json(metadata)
        row.last_error_class = None
        row.last_error_message = None
        _record_request_outcome(db, row, "selected")
        db.commit()
        spool.cleanup(row.id)
        return ParseStageResult(row.id, "selected")
    except Exception as exc:
        db.rollback()
        row = db.get(DiscoveryCandidate, candidate_id)
        if row:
            metadata, pipeline = _pipeline_metadata(row)
            pipeline["stage"] = "index_failed"
            row.metadata_json = _json(metadata)
            row.retry_count += 1
            row.next_attempt_at = datetime.now(UTC) + timedelta(
                seconds=min(settings.evidence_retry_backoff_seconds * 2 ** max(0, row.retry_count - 1), 3600)
            )
            row.last_error_class = type(exc).__name__
            row.last_error_message = str(exc)[:2000]
            db.commit()
        raise


def reconcile_refresh_requests(db: Session) -> int:
    updated = 0
    requests = db.scalars(
        select(EvidenceRefreshRequest).where(EvidenceRefreshRequest.status == "processing")
    ).all()
    candidates = db.scalars(select(DiscoveryCandidate)).all()
    for request in requests:
        linked = [
            row
            for row in candidates
            if json.loads(row.metadata_json or "{}").get("request_id") == request.id
        ]
        if linked and all(
            row.status in {
                CandidateStatus.SELECTED.value,
                CandidateStatus.DUPLICATE.value,
                CandidateStatus.REJECTED.value,
                CandidateStatus.EXPIRED.value,
            }
            or (
                row.status == CandidateStatus.FAILED.value
                and row.retry_count > settings.evidence_max_retries
            )
            for row in linked
        ):
            if request.selected_count:
                request.status = "complete"
            elif request.duplicate_count or request.rejected_count:
                request.status = "partial"
            else:
                request.status = "failed"
                request.error_class = "EvidenceStagesFailed"
                request.error_message = "All bounded candidates exhausted their stage retries."
            request.completed_at = datetime.now(UTC)
            updated += 1
    if updated:
        db.commit()
    return updated


def operational_counts(db: Session) -> dict[str, int]:
    counts = dict(db.execute(select(DiscoveryCandidate.status, func.count()).group_by(DiscoveryCandidate.status)).all())
    return {
        "candidate_backlog": sum(counts.get(status, 0) for status in ("discovered", "fetch_ready", "evaluating", "clustered", "failed")),
        "fetch_backlog": counts.get("fetch_ready", 0) + counts.get("failed", 0),
        "parse_backlog": counts.get("evaluating", 0),
        "index_backlog": counts.get("clustered", 0),
        "selected": counts.get("selected", 0),
        "duplicates": counts.get("duplicate", 0),
        "rejected": counts.get("rejected", 0),
    }
