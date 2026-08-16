"""Transaction-safe limits for the bounded Pass 4 official-source canary."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.evidence import DiscoveryCandidate, EvidenceSourceConfig

CANARY_GROUP = "pass4_official"


@dataclass(frozen=True)
class CanaryDecision:
    allowed: bool
    reason: str


def next_utc_day(now: datetime | None = None) -> datetime:
    current = now or datetime.now(UTC)
    return (current + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)


def _day_start(now: datetime) -> datetime:
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _lock(db: Session, scope: str) -> None:
    """Serialize budget reservations in Postgres; SQLite fixture tests are single writer."""

    if db.get_bind().dialect.name == "postgresql":
        db.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:scope))"),
            {"scope": f"evidence-canary:{scope}"},
        )


def _canary_config(config: EvidenceSourceConfig) -> bool:
    return config.canary_group == CANARY_GROUP


def discovery_allowance(
    db: Session,
    config: EvidenceSourceConfig,
    requested: int,
    *,
    now: datetime | None = None,
) -> int:
    if not _canary_config(config):
        return max(0, requested)
    current = now or datetime.now(UTC)
    start = _day_start(current)
    _lock(db, "discovery")
    global_used = db.scalar(
        select(func.count())
        .select_from(DiscoveryCandidate)
        .join(EvidenceSourceConfig, DiscoveryCandidate.source_config_id == EvidenceSourceConfig.id)
        .where(
            EvidenceSourceConfig.canary_group == CANARY_GROUP,
            DiscoveryCandidate.discovered_at >= start,
        )
    ) or 0
    source_used = db.scalar(
        select(func.count()).select_from(DiscoveryCandidate).where(
            DiscoveryCandidate.source_config_id == config.id,
            DiscoveryCandidate.discovered_at >= start,
        )
    ) or 0
    return max(
        0,
        min(
            requested,
            settings.evidence_canary_discovery_daily - global_used,
            config.daily_discovery_budget - source_used,
        ),
    )


def reserve_fetch(
    db: Session,
    row: DiscoveryCandidate,
    config: EvidenceSourceConfig,
    *,
    now: datetime | None = None,
) -> CanaryDecision:
    current = now or datetime.now(UTC)
    if not _canary_config(config):
        row.fetch_started_at = current
        db.flush()
        return CanaryDecision(True, "not_canary")
    start = _day_start(current)
    _lock(db, "fetch")
    # One full HTTP attempt per candidate per UTC day prevents retry storms from
    # silently consuming the canary budget.
    if row.fetch_started_at is not None and _utc(row.fetch_started_at) >= start:
        return CanaryDecision(False, "candidate_already_fetched_today")
    global_used = db.scalar(
        select(func.count())
        .select_from(DiscoveryCandidate)
        .join(EvidenceSourceConfig, DiscoveryCandidate.source_config_id == EvidenceSourceConfig.id)
        .where(
            EvidenceSourceConfig.canary_group == CANARY_GROUP,
            DiscoveryCandidate.fetch_started_at >= start,
        )
    ) or 0
    source_used = db.scalar(
        select(func.count()).select_from(DiscoveryCandidate).where(
            DiscoveryCandidate.source_config_id == config.id,
            DiscoveryCandidate.fetch_started_at >= start,
        )
    ) or 0
    if global_used >= settings.evidence_canary_fetch_daily:
        return CanaryDecision(False, "global_daily_fetch_budget")
    if source_used >= config.daily_fetch_budget:
        return CanaryDecision(False, "source_daily_fetch_budget")
    row.fetch_started_at = current
    db.flush()
    return CanaryDecision(True, "reserved")


def record_fetch(
    db: Session,
    row: DiscoveryCandidate,
    config: EvidenceSourceConfig,
    byte_count: int,
    *,
    now: datetime | None = None,
) -> CanaryDecision:
    current = now or datetime.now(UTC)
    row.fetched_at = current
    row.fetched_bytes = byte_count
    if not _canary_config(config):
        return CanaryDecision(True, "not_canary")
    start = _day_start(current)
    week_start = current - timedelta(days=7)
    _lock(db, "storage")

    def used_since(cutoff: datetime, *, source_only: bool = False) -> int:
        query = select(func.coalesce(func.sum(DiscoveryCandidate.fetched_bytes), 0)).where(
            DiscoveryCandidate.fetched_at >= cutoff,
            DiscoveryCandidate.id != row.id,
        )
        if source_only:
            query = query.where(DiscoveryCandidate.source_config_id == config.id)
        else:
            query = query.join(
                EvidenceSourceConfig,
                DiscoveryCandidate.source_config_id == EvidenceSourceConfig.id,
            ).where(EvidenceSourceConfig.canary_group == CANARY_GROUP)
        return int(db.scalar(query) or 0)

    global_day = used_since(start)
    source_day = used_since(start, source_only=True)
    global_week = used_since(week_start)
    if global_day + byte_count > settings.evidence_canary_storage_daily_mb * 1024 * 1024:
        return CanaryDecision(False, "global_daily_storage_budget")
    if global_week + byte_count > settings.evidence_canary_storage_seven_day_mb * 1024 * 1024:
        return CanaryDecision(False, "global_seven_day_storage_budget")
    if source_day + byte_count > config.daily_storage_budget_bytes:
        return CanaryDecision(False, "source_daily_storage_budget")
    return CanaryDecision(True, "recorded")


def reserve_selection(
    db: Session,
    row: DiscoveryCandidate,
    config: EvidenceSourceConfig,
    *,
    now: datetime | None = None,
) -> CanaryDecision:
    current = now or datetime.now(UTC)
    if not _canary_config(config):
        row.selected_at = current
        db.flush()
        return CanaryDecision(True, "not_canary")
    start = _day_start(current)
    _lock(db, "selection")
    if row.selected_at is not None:
        return CanaryDecision(True, "already_reserved")
    global_used = db.scalar(
        select(func.count())
        .select_from(DiscoveryCandidate)
        .join(EvidenceSourceConfig, DiscoveryCandidate.source_config_id == EvidenceSourceConfig.id)
        .where(
            EvidenceSourceConfig.canary_group == CANARY_GROUP,
            DiscoveryCandidate.selected_at >= start,
        )
    ) or 0
    source_used = db.scalar(
        select(func.count()).select_from(DiscoveryCandidate).where(
            DiscoveryCandidate.source_config_id == config.id,
            DiscoveryCandidate.selected_at >= start,
        )
    ) or 0
    if global_used >= settings.evidence_canary_selected_daily:
        return CanaryDecision(False, "global_daily_selection_budget")
    if source_used >= config.daily_selected_budget:
        return CanaryDecision(False, "source_daily_selection_budget")
    row.selected_at = current
    db.flush()
    return CanaryDecision(True, "reserved")
