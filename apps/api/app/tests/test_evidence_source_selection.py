from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from app.core.config import settings
from app.db.session import SessionLocal
from app.ingestion.evidence import Candidate
from app.ingestion.evidence_catalog import source_is_allowlisted
from app.models.workstation import DataSource
from app.services.evidence_operations import EvidenceSpool, discover_stage, fetch_stage
from app.services.evidence_pipeline import ensure_source_config, persist_candidate, run_source_once


def test_empty_selection_is_fail_closed(monkeypatch):
    monkeypatch.setattr(settings, "evidence_source_allowlist", " , ")
    assert not source_is_allowlisted("dawn")


@pytest.mark.usefixtures("database")
def test_selection_restricts_and_catalog_sync_does_not_reenable(monkeypatch):
    monkeypatch.setattr(settings, "evidence_source_allowlist", "dawn")
    with SessionLocal() as db:
        assert ensure_source_config(db, "dawn")[0].enabled
        blocked = ensure_source_config(db, "business_recorder")[0]
        assert not blocked.enabled
        blocked.enabled = True
        db.flush()
        assert not ensure_source_config(db, "business_recorder")[0].enabled


@pytest.mark.usefixtures("database")
def test_allowlist_does_not_activate_dormant_source(monkeypatch):
    monkeypatch.setattr(settings, "evidence_source_allowlist", "gdelt")
    with SessionLocal() as db:
        assert not ensure_source_config(db, "gdelt")[0].enabled


@pytest.mark.usefixtures("database")
def test_unknown_selection_aborts_before_source_creation(monkeypatch):
    monkeypatch.setattr(settings, "evidence_source_allowlist", "dawn,guardian_typo")
    with SessionLocal() as db:
        with pytest.raises(ValueError, match="guardian_typo"):
            ensure_source_config(db, "dawn")
        assert db.scalar(select(func.count()).select_from(DataSource)) == 0


@pytest.mark.usefixtures("database")
@pytest.mark.parametrize("staged", [True, False])
def test_excluded_discovery_does_not_fetch_or_advance_cursor(monkeypatch, staged):
    monkeypatch.setattr(settings, "evidence_source_allowlist", "")
    source = SimpleNamespace(key="dawn")  # No discovery method: it must never be called.
    with SessionLocal() as db:
        state = ensure_source_config(db, "dawn")[2]
        state.cursor_json = '{"page": 7}'
        db.commit()
        if staged:
            result = discover_stage(db, source, limit=2)
            assert result.discovered == 0
        else:
            result = run_source_once(db, source, limit=2)
            assert result.discovered == 0
        assert state.cursor_json == '{"page": 7}'
        assert state.last_attempted_at is None


@pytest.mark.usefixtures("database")
def test_queued_fetch_respects_new_selection_without_losing_candidate(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "evidence_source_allowlist", None)
    with SessionLocal() as db:
        _, config, _ = ensure_source_config(db, "dawn")
        candidate, _ = persist_candidate(db, config, Candidate(
            source_key="dawn", observed_url="https://www.dawn.com/news/selection-test",
            headline="Pakistan policy rate", publisher="Dawn",
            discovered_at=datetime.now(UTC), discovery_method="rss",
        ))
        db.commit()
        monkeypatch.setattr(settings, "evidence_source_allowlist", "business_recorder")
        result = fetch_stage(db, SimpleNamespace(key="dawn"), candidate.id, spool=EvidenceSpool(tmp_path))
        assert result.outcome == "source_not_allowlisted"
        assert candidate.status == "fetch_ready"
        assert candidate.next_attempt_at is not None
        assert candidate.fetched_at is None
        assert not list(tmp_path.iterdir())
