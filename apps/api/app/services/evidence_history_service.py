"""Conservative, resumable Pass 3 historical hydration planning."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.ingestion.evidence import CandidateStatus
from app.ingestion.evidence_catalog import TOPIC_QUERIES, build_pass1_registry
from app.models.evidence import (
    DiscoveryCandidate,
    EvidenceRefreshRequest,
    EvidenceSourceConfig,
    EvidenceSourceState,
)
from app.models.workstation import Instrument
from app.providers.evidence.sources import HttpEvidenceSource
from app.services.evidence_operations import DiscoveryStageResult, discover_stage


@dataclass(frozen=True)
class HistoricalPreset:
    key: str
    days: int
    sources: tuple[str, ...]
    max_candidates: int
    fetch_budget: int
    storage_budget_bytes: int


HISTORICAL_PRESETS = {
    "psx_12m": HistoricalPreset(
        "psx_12m", 365, ("psx_announcements",), 5000, 5000, 512 * 1024 * 1024
    ),
    "deep_company_12m": HistoricalPreset(
        "deep_company_12m",
        365,
        ("psx_announcements", "gdelt"),
        100,
        100,
        250 * 1024 * 1024,
    ),
    "news_90d": HistoricalPreset(
        "news_90d", 90, ("gdelt",), 200, 200, 250 * 1024 * 1024
    ),
}


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, default=str)


def _date_bounds(days: int, date_from: date | None, date_to: date | None) -> tuple[date, date]:
    end = date_to or datetime.now(UTC).date()
    start = date_from or end - timedelta(days=days)
    if start > end:
        raise ValueError("Historical evidence date_from must not be after date_to")
    if (end - start).days > 365:
        raise ValueError("Pass 3 historical hydration is capped at 12 months")
    return start, end


def _units(
    sources: tuple[str, ...],
    *,
    query_text: str | None,
    symbol: str | None,
    preset_key: str | None,
) -> list[dict[str, Any]]:
    units: list[dict[str, Any]] = []
    for source_key in sources:
        if source_key == "psx_announcements":
            units.append({"source_key": source_key, "symbol": symbol, "offset": 0})
        elif source_key == "gdelt" and preset_key == "news_90d":
            units.extend(
                {"source_key": "gdelt", "query": query, "topic": topic}
                for topic, query in TOPIC_QUERIES.items()
            )
        elif source_key == "gdelt":
            if not query_text:
                raise ValueError("GDELT historical hydration requires a bounded query")
            units.append({"source_key": source_key, "query": query_text, "topic": "company"})
        else:
            raise ValueError(f"Unsupported Pass 3 historical source {source_key!r}")
    return units


def _expansion_is_healthy(db: Session, sources: tuple[str, ...]) -> bool:
    cutoff = datetime.now(UTC) - timedelta(
        days=settings.evidence_historical_expansion_healthy_days
    )
    states = db.execute(
        select(EvidenceSourceConfig.source_key, EvidenceSourceState)
        .join(
            EvidenceSourceState,
            EvidenceSourceState.source_config_id == EvidenceSourceConfig.id,
        )
        .where(EvidenceSourceConfig.source_key.in_(sources))
    ).all()
    by_key = {key: state for key, state in states}
    return all(
        (state := by_key.get(key)) is not None
        and state.consecutive_failures == 0
        and state.healthy_since is not None
        and (
            state.healthy_since.replace(tzinfo=UTC)
            if state.healthy_since.tzinfo is None
            else state.healthy_since.astimezone(UTC)
        )
        <= cutoff
        for key in sources
    )


def create_historical_request(
    db: Session,
    *,
    preset_key: str,
    instrument: Instrument | None = None,
    requested_by_user_id: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    source_keys: tuple[str, ...] | None = None,
    max_candidates: int | None = None,
    fetch_budget: int | None = None,
    storage_budget_bytes: int | None = None,
) -> EvidenceRefreshRequest:
    preset = HISTORICAL_PRESETS[preset_key]
    if preset_key == "deep_company_12m" and instrument is None:
        raise ValueError("deep_company_12m requires an instrument")
    start, end = _date_bounds(preset.days, date_from, date_to)
    sources = source_keys or preset.sources
    if not set(sources).issubset(preset.sources):
        raise ValueError(f"{preset_key} only permits sources: {', '.join(preset.sources)}")
    requested_candidates = max_candidates or preset.max_candidates
    requested_fetches = fetch_budget or preset.fetch_budget
    requested_storage = storage_budget_bytes or preset.storage_budget_bytes
    expanding = (
        (end - start).days > preset.days
        or requested_candidates > preset.max_candidates
        or requested_fetches > preset.fetch_budget
        or requested_storage > preset.storage_budget_bytes
    )
    if expanding and not _expansion_is_healthy(db, sources):
        raise ValueError(
            "Historical budgets may expand only after every selected source has seven "
            "continuous healthy production days"
        )
    symbol = instrument.symbol if instrument else None
    query = (
        f'("{instrument.symbol}" OR "{instrument.name}") AND Pakistan'
        if instrument
        else None
    )
    planned_units = _units(
        sources,
        query_text=query,
        symbol=symbol,
        preset_key=preset_key,
    )
    scope_key = (
        f"deep_instrument:{instrument.id}" if instrument else f"preset:{preset_key}:{start}:{end}"
    )
    existing = db.scalar(
        select(EvidenceRefreshRequest).where(
            EvidenceRefreshRequest.request_type == "historical",
            EvidenceRefreshRequest.scope_key == scope_key,
            EvidenceRefreshRequest.preset_key == preset_key,
            EvidenceRefreshRequest.date_from == start,
            EvidenceRefreshRequest.date_to == end,
            EvidenceRefreshRequest.requested_by_user_id == requested_by_user_id,
            EvidenceRefreshRequest.status != "failed",
        )
    )
    if existing is not None:
        return existing
    row = EvidenceRefreshRequest(
        requested_by_user_id=requested_by_user_id,
        request_type="historical",
        scope_key=scope_key,
        query_text=query,
        source_keys_json=_json(sources),
        status="queued",
        priority_class="historical",
        max_candidates=requested_candidates,
        preset_key=preset_key,
        date_from=start,
        date_to=end,
        progress_json=_json(
            {
                "version": 1,
                "unit_index": 0,
                "units": planned_units,
                "completed_units": 0,
                "total_units": len(planned_units),
                "yield_count": 0,
                "halted_reason": None,
            }
        ),
        fetch_budget=requested_fetches,
        storage_budget_bytes=requested_storage,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def live_evidence_pressure(db: Session) -> int:
    """Count durable live work competing for shared downstream capacity."""

    nonterminal = {
        CandidateStatus.DISCOVERED.value,
        CandidateStatus.FETCH_READY.value,
        CandidateStatus.EVALUATING.value,
        CandidateStatus.CLUSTERED.value,
        CandidateStatus.FAILED.value,
    }
    pressure = 0
    for row in db.scalars(
        select(DiscoveryCandidate).where(DiscoveryCandidate.status.in_(nonterminal))
    ):
        if json.loads(row.metadata_json or "{}").get("priority_class", "live") == "live":
            pressure += 1
    pressure += len(
        db.scalars(
            select(EvidenceRefreshRequest).where(
                EvidenceRefreshRequest.priority_class == "live",
                EvidenceRefreshRequest.status.in_(("queued", "running", "processing")),
            )
        ).all()
    )
    return pressure


def historical_must_yield(db: Session) -> bool:
    """Reserve downstream capacity for live work without starving history."""

    live_limit = max(
        1,
        settings.evidence_fetch_queue_target
        - settings.evidence_historical_live_backlog_reserve,
    )
    return live_evidence_pressure(db) >= live_limit


def _source_circuit_open(db: Session, source_key: str) -> bool:
    now = datetime.now(UTC)
    state = db.scalar(
        select(EvidenceSourceState)
        .join(
            EvidenceSourceConfig,
            EvidenceSourceConfig.id == EvidenceSourceState.source_config_id,
        )
        .where(EvidenceSourceConfig.source_key == source_key)
    )
    if state is None or state.consecutive_failures < settings.evidence_circuit_failure_threshold:
        return False
    next_poll_at = state.next_poll_at
    if next_poll_at is None:
        return False
    if next_poll_at.tzinfo is None:
        next_poll_at = next_poll_at.replace(tzinfo=UTC)
    return next_poll_at > now


def _source_for_unit(unit: dict[str, Any]):
    source = build_pass1_registry().get(str(unit["source_key"]))
    if unit["source_key"] == "gdelt":
        if not isinstance(source, HttpEvidenceSource):
            raise RuntimeError("Configured GDELT source has the wrong adapter type")
        source.query = str(unit["query"])
    return source


def _initialize_legacy_request(db: Session, request: EvidenceRefreshRequest) -> dict[str, Any]:
    """Upgrade a queued Pass 2 historical row into a resumable Pass 3 plan."""

    progress = json.loads(request.progress_json or "{}")
    if progress.get("units"):
        return progress
    instrument = None
    if request.scope_key.startswith("deep_instrument:"):
        instrument = db.get(Instrument, request.scope_key.split(":", 1)[1])
    preset_key = "deep_company_12m" if instrument else "news_90d"
    preset = HISTORICAL_PRESETS[preset_key]
    end = request.date_to or datetime.now(UTC).date()
    start = request.date_from or end - timedelta(days=preset.days)
    sources = preset.sources
    query = request.query_text
    progress = {
        "version": 1,
        "unit_index": 0,
        "units": _units(
            sources,
            query_text=query,
            symbol=instrument.symbol if instrument else None,
            preset_key=preset_key,
        ),
        "completed_units": 0,
        "total_units": len(sources) if preset_key == "deep_company_12m" else len(TOPIC_QUERIES),
        "yield_count": 0,
        "halted_reason": None,
        "upgraded_from_pass2": True,
    }
    request.preset_key = preset_key
    request.date_from = start
    request.date_to = end
    request.source_keys_json = _json(sources)
    request.progress_json = _json(progress)
    db.commit()
    return progress


def run_historical_discovery_slice(
    db: Session,
    request: EvidenceRefreshRequest,
) -> tuple[DiscoveryStageResult | None, str]:
    """Run at most one bounded discovery page and persist its resume cursor."""

    progress = _initialize_legacy_request(db, request)
    if historical_must_yield(db):
        progress["yield_count"] = int(progress.get("yield_count", 0)) + 1
        progress["halted_reason"] = "yielding_to_live_work"
        request.progress_json = _json(progress)
        request.status = "queued"
        request.completed_at = None
        db.commit()
        return None, "yielded_to_live"
    remaining = request.max_candidates - request.discovered_count
    if remaining <= 0:
        progress["halted_reason"] = "candidate_budget_reached"
        request.progress_json = _json(progress)
        request.status = "processing" if request.discovered_count else "partial"
        db.commit()
        return None, "candidate_budget_reached"
    unit_index = int(progress.get("unit_index", 0))
    units = list(progress.get("units", []))
    if unit_index >= len(units):
        request.status = "processing" if request.discovered_count else "complete"
        request.completed_at = None if request.discovered_count else datetime.now(UTC)
        progress["halted_reason"] = None
        request.progress_json = _json(progress)
        db.commit()
        return None, "discovery_complete"

    unit = dict(units[unit_index])
    if _source_circuit_open(db, str(unit["source_key"])):
        progress["yield_count"] = int(progress.get("yield_count", 0)) + 1
        progress["halted_reason"] = f"source_circuit_open:{unit['source_key']}"
        request.progress_json = _json(progress)
        request.status = "queued"
        request.completed_at = None
        db.commit()
        return None, "source_circuit_open"
    batch_limit = min(settings.evidence_historical_batch_candidates, remaining)
    cursor = {
        "historical_days": (request.date_to - request.date_from).days,
        "date_from": request.date_from.isoformat(),
        "date_to": request.date_to.isoformat(),
        **{key: value for key, value in unit.items() if key in {"offset", "symbol"}},
    }
    result = discover_stage(
        db,
        _source_for_unit(unit),
        limit=batch_limit,
        priority_class="historical",
        cursor_override=cursor,
        request_id=request.id,
    )
    db.refresh(request)
    if unit["source_key"] == "psx_announcements" and result.discovered >= batch_limit:
        unit["offset"] = int(unit.get("offset", 0)) + result.discovered
        units[unit_index] = unit
    else:
        unit_index += 1
    progress.update(
        {
            "unit_index": unit_index,
            "units": units,
            "completed_units": unit_index,
            "last_slice_discovered": result.discovered,
            "last_slice_new": result.new,
            "last_slice_at": datetime.now(UTC).isoformat(),
            "halted_reason": None,
        }
    )
    request.progress_json = _json(progress)
    request.status = "queued" if unit_index < len(units) else "processing"
    request.completed_at = None
    if not result.candidate_ids and unit_index >= len(units):
        request.status = "complete" if request.discovered_count == 0 else "processing"
        if request.status == "complete":
            request.completed_at = datetime.now(UTC)
    db.commit()
    return result, "slice_complete"
