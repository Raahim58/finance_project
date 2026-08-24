"""Pass 2 Celery tasks; payloads contain IDs and bounded configuration only."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import func, select

from app.celery_app import celery_app
from app.core.config import settings
from app.db.session import SessionLocal
from app.ingestion.evidence_catalog import build_pass1_registry
from app.models.evidence import DiscoveryCandidate, EvidenceRefreshRequest, EvidenceSourceConfig
from app.providers.evidence.sources import HttpEvidenceSource
from app.services.evidence_operations import discover_stage, fetch_stage, index_stage, parse_stage
from app.services.event_intelligence_service import normalize_raw_event
from app.models.workstation import EventSource
from app.services.evidence_history_service import run_historical_discovery_slice

NETWORK_RETRY = {
    "autoretry_for": (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError),
    "retry_backoff": True,
    "retry_backoff_max": 900,
    "retry_jitter": True,
    "max_retries": 3,
}


def _priority(priority_class: str) -> int:
    return 8 if priority_class == "historical" else 0


def _source_for_candidate(db, candidate_id: str):
    row = db.get(DiscoveryCandidate, candidate_id)
    if row is None:
        raise ValueError("Evidence candidate not found")
    source_key = db.scalar(
        select(EvidenceSourceConfig.source_key).where(EvidenceSourceConfig.id == row.source_config_id)
    )
    return build_pass1_registry().get(source_key), row


def _gdelt_source(query: str) -> HttpEvidenceSource:
    source = build_pass1_registry().get("gdelt")
    if not isinstance(source, HttpEvidenceSource):
        raise RuntimeError("Configured GDELT source has the wrong adapter type")
    source.query = query
    return source


def _publish_with_capacity(candidate_id: str, task, queue: str, priority: int, stage: str) -> bool:
    status = {
        "fetch": "fetch_ready",
        "parse": "evaluating",
        "index": "clustered",
    }[stage]
    target = {
        "fetch": settings.evidence_fetch_queue_target,
        "parse": settings.evidence_parse_queue_target,
        "index": settings.evidence_index_queue_target,
    }[stage]
    now = datetime.now(UTC)
    with SessionLocal() as db:
        inflight = db.scalar(
            select(func.count()).select_from(DiscoveryCandidate).where(
                DiscoveryCandidate.status == status,
                DiscoveryCandidate.lease_expires_at > now,
            )
        ) or 0
        row = db.get(DiscoveryCandidate, candidate_id)
        if row is None or row.status != status or inflight >= target:
            return False
        row.lease_expires_at = now + timedelta(seconds=settings.evidence_stage_lease_seconds)
        db.commit()
        try:
            task.apply_async(args=(candidate_id,), queue=queue, priority=priority)
            return True
        except Exception as exc:
            row.lease_expires_at = None
            row.last_error_class = type(exc).__name__
            row.last_error_message = str(exc)[:2000]
            db.commit()
            return False


@celery_app.task(name="evidence.discover", **NETWORK_RETRY)
def discover(source_key: str, limit: int = 50, priority_class: str = "live") -> dict[str, object]:
    source = build_pass1_registry().get(source_key)
    with SessionLocal() as db:
        result = discover_stage(db, source, limit=min(max(limit, 1), 250), priority_class=priority_class)
    priority = _priority(priority_class)
    queued = sum(
        _publish_with_capacity(candidate_id, fetch, "evidence_fetch", priority, "fetch")
        for candidate_id in result.candidate_ids
    )
    return {**asdict(result), "queued": queued}


@celery_app.task(name="evidence.fetch", **NETWORK_RETRY)
def fetch(candidate_id: str) -> dict[str, object]:
    with SessionLocal() as db:
        source, row = _source_for_candidate(db, candidate_id)
        priority_class = json.loads(row.metadata_json or "{}").get("priority_class", "live")
        result = fetch_stage(db, source, candidate_id)
    if result.outcome == "raw_ready":
        task = pdf if "pdf" in (result.content_type or "").lower() else parse
        queue = "evidence_pdf" if task is pdf else "evidence_parse"
        _publish_with_capacity(
            candidate_id, task, queue, _priority(priority_class), "parse"
        )
    return asdict(result)


@celery_app.task(name="evidence.parse")
def parse(candidate_id: str) -> dict[str, object]:
    with SessionLocal() as db:
        source, row = _source_for_candidate(db, candidate_id)
        priority_class = json.loads(row.metadata_json or "{}").get("priority_class", "live")
        result = parse_stage(db, source, candidate_id)
    if result.outcome == "index_ready":
        _publish_with_capacity(
            candidate_id, index, "evidence_index", _priority(priority_class), "index"
        )
    return asdict(result)


@celery_app.task(name="evidence.pdf")
def pdf(candidate_id: str) -> dict[str, object]:
    with SessionLocal() as db:
        source, row = _source_for_candidate(db, candidate_id)
        priority_class = json.loads(row.metadata_json or "{}").get("priority_class", "live")
        result = parse_stage(db, source, candidate_id, pdf=True)
    if result.outcome == "index_ready":
        _publish_with_capacity(
            candidate_id, index, "evidence_index", _priority(priority_class), "index"
        )
    return asdict(result)


@celery_app.task(name="evidence.index")
def index(candidate_id: str) -> dict[str, object]:
    with SessionLocal() as db:
        result = index_stage(db, candidate_id)
        payload = asdict(result)
        if result.outcome in {"selected", "idempotent_selected"}:
            source = db.scalar(select(EventSource).where(EventSource.candidate_id == candidate_id))
            if source:
                payload["normalized_event_id"] = normalize_raw_event(db, source.event_id).id
        return payload


@celery_app.task(name="evidence.targeted_refresh", **NETWORK_RETRY)
def targeted_refresh(request_id: str) -> dict[str, object]:
    with SessionLocal() as db:
        request = db.get(EvidenceRefreshRequest, request_id)
        if request is None:
            raise ValueError("Evidence refresh request not found")
        if request.status in {"processing", "complete", "partial"}:
            return {"request_id": request.id, "status": request.status, "idempotent": True}
        request.status = "running"
        request.started_at = request.started_at or datetime.now(UTC)
        db.commit()
        source = _gdelt_source(request.query_text or request.scope_key)
        result = discover_stage(
            db,
            source,
            limit=request.max_candidates,
            priority_class="live",
            request_id=request.id,
        )
    queued = sum(
        _publish_with_capacity(candidate_id, fetch, "evidence_fetch", 0, "fetch")
        for candidate_id in result.candidate_ids
    )
    return {"request_id": request_id, **asdict(result), "queued": queued}


@celery_app.task(name="evidence.historical_hydrate", **NETWORK_RETRY)
def historical_hydrate(request_id: str) -> dict[str, object]:
    with SessionLocal() as db:
        request = db.get(EvidenceRefreshRequest, request_id)
        if request is None:
            raise ValueError("Historical evidence request not found")
        if request.status in {"complete", "partial"}:
            return {"request_id": request.id, "status": request.status, "idempotent": True}
        request.status = "running"
        request.started_at = request.started_at or datetime.now(UTC)
        db.commit()
        result, outcome = run_historical_discovery_slice(db, request)
    if result is None:
        return {"request_id": request_id, "outcome": outcome, "queued": 0}
    queued = sum(
        _publish_with_capacity(candidate_id, fetch, "evidence_fetch", 8, "fetch")
        for candidate_id in result.candidate_ids
    )
    return {"request_id": request_id, "outcome": outcome, **asdict(result), "queued": queued}
