"""Offline evidence clustering contracts and fixtures."""

from sqlalchemy import func, select
from app.core.config import settings
from app.db.session import SessionLocal
from app.ingestion.evidence import Candidate, ParsedEvidence
from app.models.document import Document
from app.models.evidence import DiscoveryCandidate
from app.models.workstation import Event, EventEntityLink, EventSource
from app.services.evidence_pipeline import (
    Score,
    _cluster,
    _find_duplicate,
    ensure_source_config,
    persist_candidate,
    run_source_once,
)
from app.tests.support.evidence import FixtureDawnSource, DuplicateDawnSource, ClusteredDawnSource
import pytest

pytestmark = pytest.mark.usefixtures("database")


def test_exact_body_duplicate_is_not_indexed_twice(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "source_artifact_root", str(tmp_path / "artifacts"))
    with SessionLocal() as db:
        result = run_source_once(db, DuplicateDawnSource())
        statuses = sorted(db.scalars(select(DiscoveryCandidate.status)).all())
        assert result.selected == 1
        assert result.duplicates == 1
        assert statuses == ["duplicate", "selected"]
        assert db.scalar(select(func.count()).select_from(Document)) == 1


def test_official_psx_same_title_does_not_cluster_or_deduplicate_across_symbols():
    with SessionLocal() as db:
        config = ensure_source_config(db, "psx_announcements")[1]
        candidates = []
        parsed_items = []
        for index, symbol in enumerate(("AAA", "BBB"), start=1):
            candidate = Candidate(
                "psx_announcements",
                f"https://dps.psx.com.pk/announcement/{index}",
                "Board Meeting / Closed Period",
                "Pakistan Stock Exchange",
                FixtureDawnSource.now,
                "api",
                external_id=str(index),
                metadata={"symbol": symbol},
            )
            row, _ = persist_candidate(db, config, candidate)
            parsed = ParsedEvidence(
                canonical_url=candidate.observed_url,
                title=candidate.headline,
                body="Identical exchange template body.",
                published_at=candidate.discovered_at,
                source_key=candidate.source_key,
                body_sha256="b" * 64,
                parser_method="fixture",
                extraction_quality=1.0,
                entity_keys=(symbol,),
            )
            candidates.append(row)
            parsed_items.append(parsed)

        first_score = Score(1.0, ("official_psx_announcement",), ("AAA",), "board_meeting")
        second_score = Score(1.0, ("official_psx_announcement",), ("BBB",), "board_meeting")
        first_event = _cluster(db, candidates[0], parsed_items[0], first_score)
        db.flush()

        assert _find_duplicate(db, candidates[1], parsed_items[1]) is None
        second_event = _cluster(db, candidates[1], parsed_items[1], second_score)
        assert second_event.id != first_event.id


def test_cluster_creation_reuses_deterministic_key_idempotently():
    with SessionLocal() as db:
        config = ensure_source_config(db, "psx_announcements")[1]
        candidate = Candidate(
            "psx_announcements",
            "https://dps.psx.com.pk/announcement/idempotent",
            "Voluntary Delisting",
            "Pakistan Stock Exchange",
            FixtureDawnSource.now,
            "api",
            metadata={"symbol": "PMPK"},
        )
        row, _ = persist_candidate(db, config, candidate)
        parsed = ParsedEvidence(
            canonical_url=candidate.observed_url,
            title=candidate.headline,
            body="Official voluntary delisting announcement.",
            published_at=candidate.discovered_at,
            source_key=candidate.source_key,
            body_sha256="c" * 64,
            parser_method="fixture",
            extraction_quality=1.0,
            entity_keys=("PMPK",),
        )
        score = Score(1.0, ("official_psx_announcement",), ("PMPK",), "psx_company")

        first = _cluster(db, row, parsed, score)
        db.flush()
        second = _cluster(db, row, parsed, score)

        assert second.id == first.id
        assert first.event_type == "announcement"
        assert len(db.scalars(select(Event)).all()) == 1


def test_reused_story_cluster_merges_new_entity_links():
    with SessionLocal() as db:
        config = ensure_source_config(db, "dawn")[1]
        rows = []
        parsed_items = []
        for suffix in ("first", "second"):
            candidate = Candidate(
                "dawn",
                f"https://www.dawn.com/news/{suffix}",
                "Banks respond to policy rate outlook",
                "Dawn",
                FixtureDawnSource.now,
                "rss_atom",
                external_id=suffix,
                topic="pakistan_macro",
            )
            row, _ = persist_candidate(db, config, candidate)
            rows.append(row)
            parsed_items.append(
                ParsedEvidence(
                    canonical_url=candidate.observed_url,
                    title=candidate.headline,
                    body="Pakistan banks respond to the policy rate outlook.",
                    published_at=candidate.discovered_at,
                    source_key="dawn",
                    body_sha256=suffix * 8,
                    parser_method="fixture",
                    extraction_quality=1.0,
                )
            )

        first = _cluster(db, rows[0], parsed_items[0], Score(1.0, (), ("HBL",), "pakistan_macro"))
        db.flush()
        reused = _cluster(db, rows[1], parsed_items[1], Score(1.0, (), ("MEBL",), "pakistan_macro"))
        db.flush()
        links = set(
            db.scalars(
                select(EventEntityLink.entity_key).where(EventEntityLink.event_id == first.id)
            )
        )

    assert reused.id == first.id
    assert first.event_type == "news"
    assert links == {"HBL", "MEBL"}


def test_same_story_clusters_and_keeps_one_reporting_document(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "source_artifact_root", str(tmp_path / "artifacts"))
    with SessionLocal() as db:
        result = run_source_once(db, ClusteredDawnSource())
        sources = db.scalars(select(EventSource)).all()
        assert result.selected == 1
        assert result.rejected == 1
        assert db.scalar(select(func.count()).select_from(Event)) == 1
        assert sorted(item.selection_status for item in sources) == ["reference", "selected"]
        assert db.scalar(select(func.count()).select_from(Document)) == 1
