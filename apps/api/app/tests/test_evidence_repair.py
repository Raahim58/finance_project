from datetime import UTC, datetime

from sqlalchemy import select

from app.db.session import SessionLocal
from app.ingestion.evidence import Candidate, CandidateStatus
from app.models.workstation import Event, EventSource
from app.services.evidence_pipeline import ensure_source_config, persist_candidate
from app.services.evidence_repair_service import repair_psx_role_slot_collisions


def test_psx_role_slot_repair_is_narrow_and_requeues_for_refetch():
    now = datetime(2026, 8, 16, tzinfo=UTC)
    with SessionLocal() as db:
        config = ensure_source_config(db, "psx_announcements")[1]
        event = Event(
            event_type="evidence_story",
            title="Board Meeting",
            occurred_at=now,
            topic="board_meeting",
            cluster_key="bad-cluster",
        )
        db.add(event)
        db.flush()
        candidate, _ = persist_candidate(
            db,
            config,
            Candidate(
                "psx_announcements",
                "https://dps.psx.com.pk/announcement/rejected",
                "Board Meeting",
                "Pakistan Stock Exchange",
                now,
                "api",
                metadata={"symbol": "AAA", "_pipeline": {"stage": "raw_ready"}},
            ),
        )
        candidate.status = CandidateStatus.REJECTED.value
        candidate.event_id = event.id
        candidate.body_sha256 = "a" * 64
        db.add(
            EventSource(
                event_id=event.id,
                candidate_id=candidate.id,
                source_url=candidate.observed_url,
                source_name=candidate.publisher,
                evidence_role="primary",
                selection_status="reference",
                selection_reasons_json='["role_slot_occupied"]',
            )
        )
        db.flush()

        dry_run = repair_psx_role_slot_collisions(db)
        assert dry_run.eligible == 1
        assert candidate.status == CandidateStatus.REJECTED.value

        applied = repair_psx_role_slot_collisions(db, apply=True)
        assert applied.requeued == 1
        assert candidate.status == CandidateStatus.FETCH_READY.value
        assert candidate.event_id is None
        assert candidate.body_sha256 is None
        assert "_pipeline" not in candidate.metadata_json
        assert db.scalar(select(EventSource).where(EventSource.candidate_id == candidate.id)) is None
