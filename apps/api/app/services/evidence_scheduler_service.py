"""Postgres-led Pass 2 scheduling, reconstruction, retention, and backpressure."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.ingestion.evidence import CandidateStatus
from app.ingestion.evidence_catalog import SOURCE_SPECS
from app.jobs import evidence_tasks
from app.models.evidence import (
    DiscoveryCandidate,
    EvidenceRefreshRequest,
    EvidenceSourceConfig,
    EvidenceSourceState,
)
from app.models.workstation import DataSource, Event, EventSource, Instrument
from app.services.evidence_operations import EvidenceSpool, operational_counts, reconcile_refresh_requests
from app.services.evidence_history_service import (
    create_historical_request,
    historical_must_yield,
)
from app.services.evidence_pipeline import _transition, ensure_source_config
from app.services.screening_service import deep_instrument_ids


@dataclass(frozen=True)
class SchedulerResult:
    discovery_queued: int
    fetch_queued: int
    parse_queued: int
    index_queued: int
    historical_queued: int
    expired: int
    stale_spool_removed: int
    requests_reconciled: int


def _historical_request_order_key(request: EvidenceRefreshRequest) -> tuple[object, ...]:
    """Prioritize corpus-wide presets before the large per-company request set."""

    preset_order = {"psx_12m": 0, "news_90d": 1, "deep_company_12m": 2}
    return (
        request.priority_class == "historical",
        preset_order.get(request.preset_key or "", 3),
        request.updated_at,
        request.created_at,
    )
def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _priority(row: DiscoveryCandidate) -> int:
    return 8 if json.loads(row.metadata_json or "{}").get("priority_class") == "historical" else 0


def _publish(task, candidate: DiscoveryCandidate, queue: str) -> bool:
    try:
        task.apply_async(args=(candidate.id,), queue=queue, priority=_priority(candidate))
        return True
    except Exception as exc:
        candidate.lease_expires_at = None
        candidate.last_error_class = type(exc).__name__
        candidate.last_error_message = str(exc)[:2000]
        return False


def _reserve_candidates(
    db: Session,
    rows: list[DiscoveryCandidate],
    task,
    queue: str,
    capacity: int,
) -> int:
    now = datetime.now(UTC)
    queued = 0
    for row in rows[: max(0, capacity)]:
        row.lease_expires_at = now + timedelta(seconds=settings.evidence_stage_lease_seconds)
        db.commit()
        if _publish(task, row, queue):
            queued += 1
        db.commit()
    return queued


def _candidate_stage(row: DiscoveryCandidate) -> str | None:
    return json.loads(row.metadata_json or "{}").get("_pipeline", {}).get("stage")


def _expire_old_candidates(db: Session, now: datetime) -> int:
    cutoff = now - timedelta(days=settings.evidence_candidate_retention_days)
    rows = db.scalars(
        select(DiscoveryCandidate).where(
            DiscoveryCandidate.discovered_at < cutoff,
            DiscoveryCandidate.status.in_(("discovered", "fetch_ready", "evaluating", "clustered", "failed")),
        )
    ).all()
    spool = EvidenceSpool()
    for row in rows:
        _transition(row, CandidateStatus.EXPIRED)
        row.lease_expires_at = None
        spool.cleanup(row.id)
    if rows:
        db.commit()
    return len(rows)


def create_deep_historical_requests(db: Session, *, max_new: int | None = None) -> int:
    capacity = max_new if max_new is not None else settings.evidence_historical_queue_target
    created = 0
    for instrument_id in sorted(deep_instrument_ids(db)):
        if created >= capacity:
            break
        instrument = db.get(Instrument, instrument_id)
        if instrument is None:
            continue
        scope_key = f"deep_instrument:{instrument.id}"
        exists = db.scalar(
            select(EvidenceRefreshRequest.id).where(
                EvidenceRefreshRequest.request_type == "historical",
                EvidenceRefreshRequest.scope_key == scope_key,
            )
        )
        if exists:
            continue
        create_historical_request(
            db,
            preset_key="deep_company_12m",
            instrument=instrument,
        )
        created += 1
    return created


def run_evidence_scheduler_once(db: Session) -> SchedulerResult:
    now = datetime.now(UTC)
    for spec in SOURCE_SPECS:
        ensure_source_config(db, spec.key)
    db.commit()

    expired = _expire_old_candidates(db, now)
    actionable_fetch_backlog = db.scalar(
        select(func.count()).select_from(DiscoveryCandidate).where(
            or_(
                DiscoveryCandidate.next_attempt_at.is_(None),
                DiscoveryCandidate.next_attempt_at <= now,
            ),
            or_(
                DiscoveryCandidate.status == CandidateStatus.FETCH_READY.value,
                (
                    DiscoveryCandidate.status == CandidateStatus.FAILED.value
                )
                & (DiscoveryCandidate.retry_count <= settings.evidence_max_retries),
            )
        )
    ) or 0
    discovery_queued = 0
    if actionable_fetch_backlog < settings.evidence_fetch_queue_target:
        due = db.execute(
            select(EvidenceSourceConfig, EvidenceSourceState)
            .join(EvidenceSourceState, EvidenceSourceState.source_config_id == EvidenceSourceConfig.id)
            .join(DataSource, DataSource.id == EvidenceSourceConfig.data_source_id)
            .where(
                DataSource.enabled.is_(True),
                or_(EvidenceSourceState.next_poll_at.is_(None), EvidenceSourceState.next_poll_at <= now),
            )
            .order_by(EvidenceSourceState.next_poll_at)
            .limit(settings.evidence_discovery_queue_target)
        ).all()
        for config, state in due:
            state.last_attempted_at = now
            state.next_poll_at = now + timedelta(seconds=config.poll_interval_seconds)
            db.commit()
            try:
                evidence_tasks.discover.apply_async(
                    args=(config.source_key, min(50, settings.evidence_fetch_queue_target)),
                    queue="evidence_discovery",
                    priority=0,
                )
                discovery_queued += 1
            except Exception as exc:
                state.last_error_class = type(exc).__name__
                state.last_error_message = str(exc)[:2000]
                state.next_poll_at = now + timedelta(seconds=settings.evidence_retry_backoff_seconds)
                db.commit()

    candidates = db.scalars(select(DiscoveryCandidate).order_by(DiscoveryCandidate.discovered_at)).all()
    live_first = sorted(candidates, key=lambda row: (_priority(row), row.discovered_at))
    eligible_fetch: list[DiscoveryCandidate] = []
    eligible_parse: list[DiscoveryCandidate] = []
    eligible_index: list[DiscoveryCandidate] = []
    for row in live_first:
        lease_expires_at = _utc(row.lease_expires_at)
        next_attempt_at = _utc(row.next_attempt_at)
        lease_available = lease_expires_at is None or lease_expires_at <= now
        retry_due = next_attempt_at is None or next_attempt_at <= now
        if row.status == CandidateStatus.FAILED.value and retry_due and row.retry_count <= settings.evidence_max_retries:
            _transition(row, CandidateStatus.FETCH_READY)
            row.lease_expires_at = None
        if row.status == CandidateStatus.FETCH_READY.value and lease_available and retry_due:
            eligible_fetch.append(row)
        elif row.status == CandidateStatus.EVALUATING.value and lease_available:
            if _candidate_stage(row) == "raw_ready":
                eligible_parse.append(row)
            elif lease_expires_at is not None and lease_expires_at <= now:
                _transition(row, CandidateStatus.FAILED)
                row.retry_count += 1
                row.next_attempt_at = now + timedelta(seconds=settings.evidence_retry_backoff_seconds)
        elif row.status == CandidateStatus.CLUSTERED.value and lease_available and retry_due:
            source = db.scalar(
                select(EventSource).where(
                    EventSource.candidate_id == row.id,
                    EventSource.selection_status == "pending",
                )
            )
            if source and row.retry_count <= settings.evidence_max_retries:
                eligible_index.append(row)
            elif source:
                source.selection_status = "failed"
                source.selection_reasons_json = '["index_retries_exhausted"]'
                _transition(row, CandidateStatus.FAILED)
                EvidenceSpool().cleanup(row.id)
    db.commit()

    fetch_inflight = sum(
        row.status == CandidateStatus.FETCH_READY.value
        and row.lease_expires_at is not None
        and _utc(row.lease_expires_at) > now
        for row in candidates
    )
    parse_inflight = sum(
        row.status == CandidateStatus.EVALUATING.value
        and row.lease_expires_at is not None
        and _utc(row.lease_expires_at) > now
        for row in candidates
    )
    index_inflight = sum(
        row.status == CandidateStatus.CLUSTERED.value
        and row.lease_expires_at is not None
        and _utc(row.lease_expires_at) > now
        for row in candidates
    )
    fetch_capacity = (
        min(settings.evidence_fetch_queue_target, settings.evidence_canary_fetch_ready_target)
        - fetch_inflight
    )
    parse_capacity = settings.evidence_parse_queue_target - parse_inflight
    index_capacity = settings.evidence_index_queue_target - index_inflight
    fetch_queued = _reserve_candidates(
        db, eligible_fetch, evidence_tasks.fetch, "evidence_fetch", fetch_capacity
    )
    parse_queued = 0
    for row in eligible_parse[: max(0, parse_capacity)]:
        content_type = json.loads(row.metadata_json or "{}").get("_pipeline", {}).get("content_type", "")
        task = evidence_tasks.pdf if "pdf" in content_type.lower() else evidence_tasks.parse
        queue = "evidence_pdf" if task is evidence_tasks.pdf else "evidence_parse"
        parse_queued += _reserve_candidates(db, [row], task, queue, 1)
    index_queued = _reserve_candidates(
        db, eligible_index, evidence_tasks.index, "evidence_index", index_capacity
    )

    create_deep_historical_requests(db)
    historical_queued = 0
    stale_request_cutoff = now - timedelta(seconds=settings.evidence_stage_lease_seconds)
    for request in db.scalars(
        select(EvidenceRefreshRequest).where(
            EvidenceRefreshRequest.status == "running",
            or_(
                EvidenceRefreshRequest.started_at.is_(None),
                EvidenceRefreshRequest.started_at <= stale_request_cutoff,
            ),
        )
    ):
        request.status = "queued"
    db.commit()
    requests = db.scalars(
        select(EvidenceRefreshRequest)
        .where(EvidenceRefreshRequest.status == "queued")
    ).all()
    # Keep the two corpus-wide bootstrap presets moving alongside the much larger
    # set of per-company requests. Pure creation-time FIFO lets 100+ company rows
    # starve news_90d indefinitely.
    requests.sort(key=_historical_request_order_key)
    live_queued = 0
    history_is_yielding = historical_must_yield(db)
    for request in requests:
        if request.priority_class == "historical" and history_is_yielding:
            continue
        if request.priority_class == "historical" and historical_queued >= settings.evidence_historical_queue_target:
            continue
        if request.priority_class == "live" and live_queued >= settings.evidence_discovery_queue_target:
            continue
        task = (
            evidence_tasks.historical_hydrate
            if request.priority_class == "historical"
            else evidence_tasks.targeted_refresh
        )
        queue = "historical_hydrate" if request.priority_class == "historical" else "evidence_discovery"
        priority = 8 if request.priority_class == "historical" else 0
        request.status = "running"
        request.started_at = request.started_at or now
        db.commit()
        try:
            task.apply_async(args=(request.id,), queue=queue, priority=priority)
            if request.priority_class == "historical":
                historical_queued += 1
            else:
                live_queued += 1
        except Exception as exc:
            request.status = "queued"
            request.error_class = type(exc).__name__
            request.error_message = str(exc)[:2000]
            db.commit()

    stale_spool_removed = EvidenceSpool().prune(
        now - timedelta(hours=settings.evidence_spool_retention_hours)
    )
    requests_reconciled = reconcile_refresh_requests(db)
    return SchedulerResult(
        discovery_queued,
        fetch_queued,
        parse_queued,
        index_queued,
        historical_queued,
        expired,
        stale_spool_removed,
        requests_reconciled,
    )


def evidence_operational_status(db: Session) -> dict[str, object]:
    now = datetime.now(UTC)
    global_counts = operational_counts(db)
    candidates = db.scalars(select(DiscoveryCandidate)).all()
    global_counts["live_candidates"] = sum(
        json.loads(row.metadata_json or "{}").get("priority_class", "live") == "live"
        for row in candidates
    )
    global_counts["historical_candidates"] = sum(
        json.loads(row.metadata_json or "{}").get("priority_class") == "historical"
        for row in candidates
    )
    global_counts["historical_requests"] = dict(
        db.execute(
            select(EvidenceRefreshRequest.status, func.count())
            .where(EvidenceRefreshRequest.priority_class == "historical")
            .group_by(EvidenceRefreshRequest.status)
        ).all()
    )
    global_counts["historical_fetched_bytes"] = db.scalar(
        select(func.coalesce(func.sum(EvidenceRefreshRequest.fetched_bytes), 0)).where(
            EvidenceRefreshRequest.priority_class == "historical"
        )
    )
    global_counts["historical_storage_budget_bytes"] = db.scalar(
        select(func.coalesce(func.sum(EvidenceRefreshRequest.storage_budget_bytes), 0)).where(
            EvidenceRefreshRequest.priority_class == "historical"
        )
    )
    parsed_count = sum(row.parser_version is not None for row in candidates)
    global_counts["extraction_success_rate"] = (
        parsed_count / max(1, sum(row.status != "fetch_ready" for row in candidates))
    )
    event_count = db.scalar(
        select(func.count()).select_from(Event).where(Event.event_type == "evidence_story")
    ) or 0
    selected_sources = db.scalar(
        select(func.count()).select_from(EventSource).where(EventSource.selection_status == "selected")
    ) or 0
    global_counts["average_retained_documents_per_story"] = selected_sources / max(1, event_count)
    source_rows = db.execute(
        select(EvidenceSourceConfig, EvidenceSourceState).join(
            EvidenceSourceState, EvidenceSourceState.source_config_id == EvidenceSourceConfig.id
        )
    ).all()
    sources = []
    for config, state in source_rows:
        source_candidates = [row for row in candidates if row.source_config_id == config.id]
        status_counts = dict(
            db.execute(
                select(DiscoveryCandidate.status, func.count())
                .where(DiscoveryCandidate.source_config_id == config.id)
                .group_by(DiscoveryCandidate.status)
            ).all()
        )
        diagnostics = json.loads(state.diagnostics_json or "{}")
        discovered = len(source_candidates)
        relevant = sum(
            row.relevance_score is not None and float(row.relevance_score) >= 0.30
            for row in source_candidates
        )
        # Pre-0018 rows have no fetch timestamps. A parser version proves that a
        # full response was fetched, so include it in the compatibility count.
        fetched = sum(
            row.fetched_at is not None or row.parser_version is not None
            for row in source_candidates
        )
        extracted = sum(row.parser_version is not None for row in source_candidates)
        non_duplicate = sum(
            row.parser_version is not None and row.status != CandidateStatus.DUPLICATE.value
            for row in source_candidates
        )
        unique_stories = len({row.event_id for row in source_candidates if row.event_id})
        selected = sum(row.status == CandidateStatus.SELECTED.value for row in source_candidates)
        unique_story_rate = unique_stories / max(1, fetched)
        evidence_selection_rate = selected / max(1, fetched)
        if fetched < 100:
            canary_signal = "collecting"
        elif unique_story_rate < 0.01 and evidence_selection_rate < 0.01:
            canary_signal = "review_low_yield"
        else:
            canary_signal = "healthy"
        sources.append(
            {
                "source_key": config.source_key,
                "source_tier": config.source_tier,
                "last_attempted_at": state.last_attempted_at,
                "last_success_at": state.last_success_at,
                "next_poll_at": state.next_poll_at,
                "freshness_seconds": (
                    (now - _utc(state.last_success_at)).total_seconds()
                    if state.last_success_at
                    else None
                ),
                "consecutive_failures": state.consecutive_failures,
                "circuit_open_until": diagnostics.get("circuit_open_until"),
                "last_error_class": state.last_error_class,
                "last_error_message": state.last_error_message,
                "counts": status_counts,
                "funnel": {
                    "discovered": discovered,
                    "relevant": relevant,
                    "fetched": fetched,
                    "successfully_extracted": extracted,
                    "non_duplicate": non_duplicate,
                    "unique_story": unique_stories,
                    "selected_as_best_evidence": selected,
                    "unique_story_rate": unique_story_rate,
                    "evidence_selection_rate": evidence_selection_rate,
                    "signal": canary_signal,
                },
                "canary": {
                    "group": config.canary_group,
                    "daily_discovery_budget": config.daily_discovery_budget,
                    "daily_fetch_budget": config.daily_fetch_budget,
                    "daily_selected_budget": config.daily_selected_budget,
                    "daily_storage_budget_bytes": config.daily_storage_budget_bytes,
                },
                "provenance": json.loads(config.provenance_json or "{}"),
                "fallback": json.loads(config.fallback_json or "{}"),
            }
        )
    global_counts["source_health"] = sources
    return global_counts
