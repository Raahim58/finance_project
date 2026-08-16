"""Narrow, auditable repairs for evidence pipeline classification defects."""

from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ingestion.evidence import CandidateStatus
from app.models.evidence import DiscoveryCandidate, EvidenceSourceConfig
from app.models.workstation import EventSource


@dataclass(frozen=True)
class RepairResult:
    eligible: int
    requeued: int
    skipped_historical: int


def repair_psx_role_slot_collisions(
    db: Session,
    *,
    apply: bool = False,
    limit: int = 1000,
) -> RepairResult:
    """Requeue only PSX rows rejected by the cross-issuer role-slot defect.

    Historical-request rows are excluded because changing their terminal counters
    also requires reopening the owning request. Ordinary relevance and duplicate
    decisions are never selected by this repair.
    """

    rows = db.execute(
        select(DiscoveryCandidate, EventSource)
        .join(EvidenceSourceConfig, EvidenceSourceConfig.id == DiscoveryCandidate.source_config_id)
        .join(EventSource, EventSource.candidate_id == DiscoveryCandidate.id)
        .where(
            EvidenceSourceConfig.source_key == "psx_announcements",
            DiscoveryCandidate.status == CandidateStatus.REJECTED.value,
            EventSource.selection_status == "reference",
            EventSource.selection_reasons_json == '["role_slot_occupied"]',
        )
        .order_by(DiscoveryCandidate.discovered_at, DiscoveryCandidate.id)
        .limit(limit)
        .with_for_update(of=DiscoveryCandidate, skip_locked=True)
    ).all()
    eligible = 0
    requeued = 0
    skipped_historical = 0
    for candidate, event_source in rows:
        metadata = json.loads(candidate.metadata_json or "{}")
        if metadata.get("request_id"):
            skipped_historical += 1
            continue
        eligible += 1
        if not apply:
            continue
        metadata.pop("_pipeline", None)
        candidate.metadata_json = json.dumps(metadata, sort_keys=True, default=str)
        candidate.status = CandidateStatus.FETCH_READY.value
        candidate.event_id = None
        candidate.artifact_id = None
        candidate.body_sha256 = None
        candidate.simhash = None
        candidate.novelty_score = None
        candidate.lease_expires_at = None
        candidate.next_attempt_at = None
        candidate.last_error_class = None
        candidate.last_error_message = None
        candidate.scoring_reasons_json = '["requeued_after_psx_cross_issuer_cluster_fix"]'
        candidate.configuration_version = "evidence-v1-psx-issuer-cluster-v2"
        db.delete(event_source)
        requeued += 1
    db.flush()
    return RepairResult(eligible, requeued, skipped_historical)


def repair_pass4_relative_rss_urls(
    db: Session,
    *,
    apply: bool = False,
    limit: int = 1000,
) -> RepairResult:
    """Repair only Pass 4 rows failed by the relative-RSS-link adapter defect."""

    rows = db.scalars(
        select(DiscoveryCandidate)
        .join(EvidenceSourceConfig, EvidenceSourceConfig.id == DiscoveryCandidate.source_config_id)
        .where(
            EvidenceSourceConfig.canary_group == "pass4_official",
            DiscoveryCandidate.status == CandidateStatus.FETCH_READY.value,
            DiscoveryCandidate.last_error_class == "ValueError",
            DiscoveryCandidate.last_error_message == "Evidence fetch requires an HTTP(S) URL",
            DiscoveryCandidate.canonical_url.like("http%"),
        )
        .order_by(DiscoveryCandidate.discovered_at, DiscoveryCandidate.id)
        .limit(limit)
        .with_for_update(skip_locked=True)
    ).all()
    eligible = len(rows)
    if apply:
        for candidate in rows:
            candidate.observed_url = candidate.canonical_url
            candidate.fetch_started_at = None
            candidate.lease_expires_at = None
            candidate.next_attempt_at = None
            candidate.last_error_class = None
            candidate.last_error_message = None
            candidate.scoring_reasons_json = '["requeued_after_relative_rss_url_fix"]'
        db.flush()
    return RepairResult(eligible, eligible if apply else 0, 0)
