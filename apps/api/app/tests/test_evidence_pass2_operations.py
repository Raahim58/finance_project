import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.db.session import SessionLocal
from app.ingestion.evidence import Candidate, DiscoveryBatch, RawContent
from app.models.document import Document
from app.models.evidence import DiscoveryCandidate, EvidenceRefreshRequest, EvidenceSourceState
from app.models.workstation import EventSource, Instrument
from app.services.evidence_operations import (
    EvidenceSpool,
    discover_stage,
    fetch_stage,
    index_stage,
    parse_stage,
)
from app.services.evidence_pipeline import ensure_source_config, persist_candidate
from app.services.evidence_scheduler_service import (
    create_deep_historical_requests,
    run_evidence_scheduler_once,
)


NOW = datetime(2026, 8, 14, 10, 0, tzinfo=UTC)


class StagedDawnSource:
    key = "dawn"

    def discover_since(self, cursor, limit):
        del cursor
        candidate = Candidate(
            source_key=self.key,
            observed_url="https://www.dawn.com/news/staged-pass2",
            canonical_url="https://www.dawn.com/news/staged-pass2",
            external_id="staged-pass2",
            headline="Pakistan inflation and SBP policy rate outlook",
            publisher="Dawn",
            discovered_at=NOW,
            published_at=NOW,
            discovery_method="rss_atom",
            topic="pakistan_macro",
        )
        return DiscoveryBatch((candidate,)[:limit], {"last_id": candidate.external_id})

    def fetch(self, candidate):
        html = b'''<html><script type="application/ld+json">{"@type":"NewsArticle","headline":"Pakistan inflation and SBP policy rate outlook","datePublished":"2026-08-14T10:00:00Z","articleBody":"Pakistan inflation and the SBP policy rate remain central to the current economic outlook and reserve position."}</script></html>'''
        return RawContent(candidate, html, "text/html", NOW, candidate.observed_url)

    def normalize(self, raw):
        from app.providers.evidence.extraction import extract_article

        return extract_article(raw)


def test_staged_pipeline_spools_then_indexes_selected_evidence(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "source_artifact_root", str(tmp_path / "artifacts"))
    spool = EvidenceSpool(tmp_path)
    source = StagedDawnSource()
    with SessionLocal() as db:
        discovered = discover_stage(db, source, limit=10)
        candidate_id = discovered.candidate_ids[0]
        fetched = fetch_stage(db, source, candidate_id, spool=spool)
        parsed = parse_stage(db, source, candidate_id, spool=spool)

        assert fetched.outcome == "raw_ready"
        assert parsed.outcome == "index_ready"
        assert db.get(DiscoveryCandidate, candidate_id).status == "clustered"
        assert db.scalar(select(EventSource)).selection_status == "pending"
        assert spool.read_raw(candidate_id)
        assert spool.read_parsed(candidate_id).body_sha256

        indexed = index_stage(db, candidate_id, spool=spool)
        assert indexed.outcome == "selected"
        assert db.get(DiscoveryCandidate, candidate_id).status == "selected"
        assert db.scalar(select(EventSource)).selection_status == "selected"
        assert db.scalar(select(Document)).document_type == "selected_evidence"
        assert not (spool.root / f"{candidate_id}.raw").exists()


class BrokenDawnSource(StagedDawnSource):
    def discover_since(self, cursor, limit):
        raise RuntimeError("fixture source unavailable")


def test_source_circuit_opens_after_configured_failures(monkeypatch):
    monkeypatch.setattr(settings, "evidence_circuit_failure_threshold", 2)
    with SessionLocal() as db:
        for _ in range(2):
            with pytest.raises(RuntimeError, match="unavailable"):
                discover_stage(db, BrokenDawnSource(), limit=5)
        state = db.scalar(select(EvidenceSourceState))
        diagnostics = json.loads(state.diagnostics_json)
        assert state.consecutive_failures == 2
        assert state.next_poll_at is not None
        assert diagnostics["circuit_open_until"] is not None


def test_scheduler_reconstructs_live_before_historical_from_postgres(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "source_artifact_root", str(tmp_path / "artifacts"))
    monkeypatch.setattr(settings, "evidence_fetch_queue_target", 10)
    monkeypatch.setattr(settings, "evidence_candidate_retention_days", 45)
    published = []

    def capture(*, args, queue, priority):
        published.append((args[0], queue, priority))

    from app.jobs import evidence_tasks

    for task in (
        evidence_tasks.discover,
        evidence_tasks.fetch,
        evidence_tasks.parse,
        evidence_tasks.pdf,
        evidence_tasks.index,
        evidence_tasks.targeted_refresh,
        evidence_tasks.historical_hydrate,
    ):
        monkeypatch.setattr(task, "apply_async", capture)

    with SessionLocal() as db:
        _, config, _ = ensure_source_config(db, "dawn")
        candidates = []
        for suffix, priority in (("historical", "historical"), ("live", "live")):
            candidate = Candidate(
                "dawn",
                f"https://www.dawn.com/news/{suffix}",
                f"Pakistan policy rate {suffix}",
                "Dawn",
                NOW,
                "rss_atom",
                external_id=suffix,
                metadata={"priority_class": priority},
            )
            row, _ = persist_candidate(db, config, candidate)
            candidates.append(row)
        db.commit()
        for state in db.scalars(select(EvidenceSourceState)):
            state.next_poll_at = datetime.now(UTC) + timedelta(days=1)
        db.commit()
        result = run_evidence_scheduler_once(db)

        fetch_messages = [item for item in published if item[1] == "evidence_fetch"]
        assert result.fetch_queued == 2
        assert [item[2] for item in fetch_messages] == [0, 8]
        assert all(db.get(DiscoveryCandidate, row.id).lease_expires_at for row in candidates)


def _auth(client, email):
    token = client.post(
        "/auth/signup", json={"email": email, "password": "password123"}
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_targeted_refresh_request_is_bounded_owned_and_reconstructable(client, monkeypatch):
    from app.api.routes import ingestion

    monkeypatch.setattr(ingestion.targeted_refresh, "apply_async", lambda **kwargs: None)
    with SessionLocal() as db:
        db.add(Instrument(symbol="HBL", name="Habib Bank Limited", sector="Commercial Banks"))
        db.commit()
    owner = _auth(client, "evidence-owner@example.com")
    other = _auth(client, "evidence-other@example.com")
    response = client.post(
        "/ingestion/evidence/refresh",
        headers=owner,
        json={"scope_type": "symbol", "value": "hbl", "max_candidates": 20},
    )
    assert response.status_code == 202
    payload = response.json()
    assert payload["scope_key"] == "symbol:HBL"
    assert payload["priority_class"] == "live"
    assert len(client.get("/ingestion/evidence/requests", headers=owner).json()) == 1
    assert client.get("/ingestion/evidence/requests", headers=other).json() == []
    operations = client.get("/ingestion/evidence/operations", headers=owner)
    assert operations.status_code == 200
    assert "source_health" in operations.json()
    with SessionLocal() as db:
        row = db.get(EvidenceRefreshRequest, payload["id"])
        assert "Habib Bank Limited" in row.query_text


def test_old_nonterminal_candidate_expires_before_scheduler_dispatch(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "source_artifact_root", str(tmp_path / "artifacts"))
    monkeypatch.setattr(settings, "evidence_candidate_retention_days", 1)
    published = []
    from app.jobs import evidence_tasks

    monkeypatch.setattr(
        evidence_tasks.fetch,
        "apply_async",
        lambda **kwargs: published.append(kwargs),
    )
    monkeypatch.setattr(evidence_tasks.discover, "apply_async", lambda **kwargs: None)
    with SessionLocal() as db:
        _, config, _ = ensure_source_config(db, "dawn")
        candidate = Candidate(
            "dawn",
            "https://www.dawn.com/news/old",
            "Pakistan old story",
            "Dawn",
            datetime.now(UTC) - timedelta(days=2),
            "rss_atom",
            external_id="old",
        )
        row, _ = persist_candidate(db, config, candidate)
        db.commit()
        result = run_evidence_scheduler_once(db)
        assert result.expired == 1
        assert db.get(DiscoveryCandidate, row.id).status == "expired"
        assert published == []


def test_deep_company_historical_request_is_bounded_and_idempotent():
    with SessionLocal() as db:
        instrument = Instrument(
            symbol="DEEP",
            name="Deep Company Limited",
            sector="Technology",
            metadata_json='{"deep_requested": true}',
        )
        db.add(instrument)
        db.commit()
        assert create_deep_historical_requests(db, max_new=5) == 1
        assert create_deep_historical_requests(db, max_new=5) == 0
        request = db.scalar(select(EvidenceRefreshRequest))
        assert request.priority_class == "historical"
        assert request.max_candidates == 100
        assert "Deep Company Limited" in request.query_text


def test_celery_routes_keep_phase2_and_evidence_queues_separate():
    from app.celery_app import celery_app

    routes = celery_app.conf.task_routes
    assert routes["phase2.dps_history"]["queue"] == "dps_history"
    assert routes["evidence.fetch"]["queue"] == "evidence_fetch"
    assert routes["evidence.pdf"]["queue"] == "evidence_pdf"
    assert routes["evidence.historical_hydrate"]["queue"] == "historical_hydrate"
    assert celery_app.conf.worker_prefetch_multiplier == 1
